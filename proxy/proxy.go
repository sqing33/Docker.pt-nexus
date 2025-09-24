// proxy.go (最终完整版 - 包含种子获取、统计、截图、MediaInfo功能)
package main

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"mime/multipart"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/superturkey650/go-qbittorrent/qbt"
)

// ======================= 结构体定义 =======================

type DownloaderConfig struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	Host     string `json:"host"`
	Username string `json:"username"`
	Password string `json:"password"`
}

// NormalizedTorrent 作为从 qBittorrent 获取数据的中间结构
type NormalizedTorrent struct {
	Hash         string
	Name         string
	Size         int64
	Progress     float64
	State        string
	SavePath     string
	Comment      string
	Trackers     []map[string]string
	Uploaded     int64
	DownloaderID string
}

// NormalizedInfo 是最终返回给 Python 项目的、模仿 _normalize_torrent_info 输出的格式
type NormalizedInfo struct {
	Hash         string              `json:"hash"`
	Name         string              `json:"name"`
	Size         int64               `json:"size"`
	Progress     float64             `json:"progress"` // 0.0-1.0 的原始值
	State        string              `json:"state"`    // 原始状态
	SavePath     string              `json:"save_path"`
	Comment      string              `json:"comment,omitempty"`
	Trackers     []map[string]string `json:"trackers"`
	Uploaded     int64               `json:"uploaded"`
	DownloaderID string              `json:"downloader_id"`
}

type TorrentsRequest struct {
	Downloaders     []DownloaderConfig `json:"downloaders"`
	IncludeComment  bool               `json:"include_comment,omitempty"`
	IncludeTrackers bool               `json:"include_trackers,omitempty"`
}

type ServerStats struct {
	DownloaderID  string `json:"downloader_id"`
	DownloadSpeed int64  `json:"download_speed"`
	UploadSpeed   int64  `json:"upload_speed"`
	TotalDownload int64  `json:"total_download"`
	TotalUpload   int64  `json:"total_upload"`
}

type FlexibleTracker struct {
	URL        string      `json:"url"`
	Status     int         `json:"status"`
	Tier       interface{} `json:"tier"`
	NumPeers   int         `json:"num_peers"`
	NumSeeds   int         `json:"num_seeds"`
	NumLeeches int         `json:"num_leeches"`
	Msg        string      `json:"msg"`
}

type qbHTTPClient struct {
	Client     *http.Client
	BaseURL    string
	IsLoggedIn bool
}

type ScreenshotRequest struct {
	RemotePath string `json:"remote_path"`
}

type ScreenshotResponse struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
	BBCode  string `json:"bbcode,omitempty"`
}

type MediaInfoRequest struct {
	RemotePath string `json:"remote_path"`
}

type MediaInfoResponse struct {
	Success       bool   `json:"success"`
	Message       string `json:"message"`
	MediaInfoText string `json:"mediainfo_text,omitempty"`
}

// ======================= 辅助函数 =======================

func newQBHTTPClient(baseURL string) (*qbHTTPClient, error) {
	jar, err := cookiejar.New(nil)
	if err != nil {
		return nil, err
	}
	return &qbHTTPClient{
		Client:  &http.Client{Jar: jar, Timeout: 30 * time.Second},
		BaseURL: baseURL,
	}, nil
}

func (c *qbHTTPClient) Login(username, password string) error {
	loginURL := fmt.Sprintf("%s/api/v2/auth/login", c.BaseURL)
	data := url.Values{}
	data.Set("username", username)
	data.Set("password", password)
	req, err := http.NewRequest("POST", loginURL, strings.NewReader(data.Encode()))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Referer", c.BaseURL)
	resp, err := c.Client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("登录失败, 状态码: %d, 响应: %s", resp.StatusCode, string(body))
	}
	if strings.TrimSpace(string(body)) != "Ok." {
		return fmt.Errorf("登录失败，响应不为 'Ok.': %s", string(body))
	}
	c.IsLoggedIn = true
	log.Printf("为 %s 登录成功", c.BaseURL)
	return nil
}

func (c *qbHTTPClient) Get(endpoint string, params url.Values) ([]byte, error) {
	if !c.IsLoggedIn {
		return nil, fmt.Errorf("客户端未登录")
	}
	fullURL := fmt.Sprintf("%s/api/v2/%s", c.BaseURL, endpoint)
	if params != nil {
		fullURL += "?" + params.Encode()
	}
	req, err := http.NewRequest("GET", fullURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Referer", c.BaseURL)
	resp, err := c.Client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GET请求 %s 失败, 状态码: %d", endpoint, resp.StatusCode)
	}
	return io.ReadAll(resp.Body)
}

func formatAndFilterTrackers(originalTrackers []map[string]string) []map[string]string {
	var formatted []map[string]string
	if originalTrackers == nil {
		return formatted
	}
	for _, tracker := range originalTrackers {
		if url, ok := tracker["url"]; ok && (strings.HasPrefix(url, "http") || strings.HasPrefix(url, "udp")) {
			formatted = append(formatted, map[string]string{"url": url})
		}
	}
	return formatted
}

func toNormalizedInfo(t NormalizedTorrent) NormalizedInfo {
	return NormalizedInfo{
		Hash: t.Hash, Name: t.Name, Size: t.Size, Progress: t.Progress, State: t.State,
		SavePath: t.SavePath, Comment: t.Comment, Trackers: formatAndFilterTrackers(t.Trackers),
		Uploaded: t.Uploaded, DownloaderID: t.DownloaderID,
	}
}

func formatTrackersForRaw(trackers []FlexibleTracker) []map[string]string {
	var result []map[string]string
	for _, tracker := range trackers {
		result = append(result, map[string]string{
			"url": tracker.URL, "status": fmt.Sprintf("%d", tracker.Status), "msg": tracker.Msg,
			"peers": fmt.Sprintf("%d", tracker.NumPeers), "seeds": fmt.Sprintf("%d", tracker.NumSeeds),
			"leeches": fmt.Sprintf("%d", tracker.NumLeeches),
		})
	}
	return result
}

func writeJSONResponse(w http.ResponseWriter, r *http.Request, statusCode int, data interface{}) {
	w.Header().Set("Content-Type", "application/json")
	jsonData, err := json.Marshal(data)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte(`{"success":false, "message":"Failed to serialize response"}`))
		return
	}
	if strings.Contains(r.Header.Get("Accept-Encoding"), "gzip") {
		w.Header().Set("Content-Encoding", "gzip")
		gz := gzip.NewWriter(w)
		defer gz.Close()
		w.WriteHeader(statusCode)
		gz.Write(jsonData)
	} else {
		w.WriteHeader(statusCode)
		w.Write(jsonData)
	}
}

// ======================= 核心业务逻辑 =======================

func fetchTorrentsForDownloader(wg *sync.WaitGroup, config DownloaderConfig, includeComment, includeTrackers bool, resultsChan chan<- []NormalizedTorrent, errChan chan<- error) {
	defer wg.Done()
	if config.Type != "qbittorrent" {
		resultsChan <- []NormalizedTorrent{}
		return
	}
	log.Printf("正在为下载器 '%s' 获取种子数据...", config.Host)
	qb := qbt.NewClient(config.Host)
	if err := qb.Login(config.Username, config.Password); err != nil {
		errChan <- fmt.Errorf("[%s] 登录失败: %v", config.Host, err)
		return
	}
	torrents, err := qb.Torrents(qbt.TorrentsOptions{})
	if err != nil {
		errChan <- fmt.Errorf("[%s] 获取种子列表失败: %v", config.Host, err)
		return
	}

	normalizedList := make([]NormalizedTorrent, 0, len(torrents))
	for _, t := range torrents {
		normalizedList = append(normalizedList, NormalizedTorrent{
			Hash: t.Hash, Name: t.Name, Size: t.Size, Progress: t.Progress, State: t.State,
			SavePath: t.SavePath, Uploaded: t.Uploaded, DownloaderID: config.ID,
		})
	}

	if includeComment || includeTrackers {
		httpClient, err := newQBHTTPClient(config.Host)
		if err != nil {
			errChan <- fmt.Errorf("[%s] 创建HTTP客户端失败: %v", config.Host, err)
			return
		}
		if err := httpClient.Login(config.Username, config.Password); err != nil {
			errChan <- fmt.Errorf("[%s] 自定义HTTP客户端登录失败: %v", config.Host, err)
			return
		}
		for i := range normalizedList {
			torrent := &normalizedList[i]
			params := url.Values{}
			params.Set("hash", torrent.Hash)
			if includeComment {
				body, err := httpClient.Get("torrents/properties", params)
				if err == nil {
					var props struct {
						Comment string `json:"comment"`
					}
					if json.Unmarshal(body, &props) == nil {
						torrent.Comment = props.Comment
					}
				}
			}
			if includeTrackers {
				body, err := httpClient.Get("torrents/trackers", params)
				if err == nil {
					var trackers []FlexibleTracker
					if json.Unmarshal(body, &trackers) == nil {
						torrent.Trackers = formatTrackersForRaw(trackers)
					}
				}
			}
		}
	}
	log.Printf("成功从 '%s' 获取到 %d 个种子", config.Host, len(normalizedList))
	resultsChan <- normalizedList
}

func fetchServerStatsForDownloader(wg *sync.WaitGroup, config DownloaderConfig, resultsChan chan<- ServerStats, errChan chan<- error) {
	defer wg.Done()
	if config.Type != "qbittorrent" {
		resultsChan <- ServerStats{DownloaderID: config.ID}
		return
	}
	log.Printf("正在为下载器 '%s' 获取统计信息...", config.Host)
	httpClient, err := newQBHTTPClient(config.Host)
	if err != nil {
		errChan <- fmt.Errorf("[%s] 创建HTTP客户端失败: %v", config.Host, err)
		return
	}
	if err := httpClient.Login(config.Username, config.Password); err != nil {
		errChan <- fmt.Errorf("[%s] 自定义HTTP客户端登录失败: %v", config.Host, err)
		return
	}
	body, err := httpClient.Get("sync/maindata", nil)
	if err != nil {
		errChan <- fmt.Errorf("[%s] 获取统计信息失败: %v", config.Host, err)
		return
	}
	var mainData struct {
		ServerState struct {
			DlInfoSpeed int64 `json:"dl_info_speed"`
			UpInfoSpeed int64 `json:"up_info_speed"`
			AlltimeDL   int64 `json:"alltime_dl"`
			AlltimeUL   int64 `json:"alltime_ul"`
		} `json:"server_state"`
	}
	if err := json.Unmarshal(body, &mainData); err != nil {
		errChan <- fmt.Errorf("[%s] 解析统计信息JSON失败: %v", config.Host, err)
		return
	}
	stats := ServerStats{
		DownloaderID: config.ID, DownloadSpeed: mainData.ServerState.DlInfoSpeed,
		UploadSpeed: mainData.ServerState.UpInfoSpeed, TotalDownload: mainData.ServerState.AlltimeDL,
		TotalUpload: mainData.ServerState.AlltimeUL,
	}
	log.Printf("成功从 '%s' 获取到服务器统计信息", config.Host)
	resultsChan <- stats
}

// ======================= [新增] 媒体处理辅助函数 =======================

func executeCommand(name string, args ...string) (string, error) {
	cmd := exec.Command(name, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	if err != nil {
		return "", fmt.Errorf("命令 '%s' 执行失败: %v, 错误输出: %s", name, err, stderr.String())
	}
	return stdout.String(), nil
}

func getVideoDuration(videoPath string) (float64, error) {
	log.Printf("正在获取视频时长: %s", videoPath)
	output, err := executeCommand("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", videoPath)
	if err != nil {
		return 0, fmt.Errorf("ffprobe 获取时长失败: %v", err)
	}
	duration, err := strconv.ParseFloat(strings.TrimSpace(output), 64)
	if err != nil {
		return 0, fmt.Errorf("解析视频时长失败: %v", err)
	}
	log.Printf("视频时长: %.2f 秒", duration)
	return duration, nil
}

func findFirstSubtitleStream(videoPath string) (int, error) {
	log.Printf("正在为视频 '%s' 探测字幕流...", filepath.Base(videoPath))

	args := []string{
		"-v", "quiet",
		"-print_format", "json",
		"-show_entries", "stream=index,codec_type,disposition",
		"-select_streams", "s",
		videoPath,
	}

	output, err := executeCommand("ffprobe", args...)
	if err != nil {
		return -1, fmt.Errorf("ffprobe 探测字幕失败: %v", err)
	}

	var probeResult struct {
		Streams []struct {
			Index       int `json:"index"`
			Disposition struct {
				Comment         int `json:"comment"`
				HearingImpaired int `json:"hearing_impaired"`
				VisualImpaired  int `json:"visual_impaired"`
			} `json:"disposition"`
		} `json:"streams"`
	}

	if err := json.Unmarshal([]byte(output), &probeResult); err != nil {
		log.Printf("警告: 解析 ffprobe 的字幕 JSON 输出失败: %v。将不带字幕截图。", err)
		return -1, nil
	}

	if len(probeResult.Streams) == 0 {
		log.Printf("视频中未发现内嵌字幕流。")
		return -1, nil
	}

	for _, stream := range probeResult.Streams {
		if stream.Disposition.Comment == 0 && stream.Disposition.HearingImpaired == 0 && stream.Disposition.VisualImpaired == 0 {
			log.Printf("   ✅ 找到可用字幕流，流索引: %d", stream.Index)
			return stream.Index, nil
		}
	}

	log.Printf("   ⚠️ 未找到\"正常\"字幕流，将使用第一个字幕流 (索引: %d)", probeResult.Streams[0].Index)
	return probeResult.Streams[0].Index, nil
}

func takeScreenshot(videoPath, outputPath string, timePoint float64, subtitleStreamIndex int) error {
	log.Printf("正在截图 (时间点: %.2fs) -> %s", timePoint, outputPath)

	args := []string{
		"-ss", fmt.Sprintf("%.2f", timePoint),
		"-i", videoPath,
		"-vframes", "1",
		"-q:v", "2",
		"-y",
	}

	if subtitleStreamIndex >= 0 {
		safeVideoPath := strings.ReplaceAll(videoPath, `\`, `\\`)
		safeVideoPath = strings.ReplaceAll(safeVideoPath, `:`, `\:`)

		filter := fmt.Sprintf("subtitles='%s':stream_index=%d", safeVideoPath, subtitleStreamIndex)

		args = append(args, "-vf", filter)
		log.Printf("   ...将使用字幕流索引 %d 进行截图。", subtitleStreamIndex)
	} else {
		log.Printf("   ...未提供字幕流，将不带字幕截图。")
	}

	args = append(args, outputPath)

	_, err := executeCommand("ffmpeg", args...)
	if err != nil {
		log.Printf("ffmpeg 截图失败，命令参数: %v", args)
		return fmt.Errorf("ffmpeg 截图失败: %v", err)
	}
	return nil
}

func uploadToPixhost(imagePath string) (string, error) {
	log.Printf("准备上传图片到 Pixhost: %s", imagePath)
	file, err := os.Open(imagePath)
	if err != nil {
		return "", err
	}
	defer file.Close()

	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	part, err := writer.CreateFormFile("img", filepath.Base(imagePath))
	if err != nil {
		return "", err
	}
	if _, err = io.Copy(part, file); err != nil {
		return "", err
	}
	if err = writer.WriteField("content_type", "0"); err != nil {
		return "", err
	}
	if err = writer.Close(); err != nil {
		return "", err
	}

	req, _ := http.NewRequest("POST", "https://api.pixhost.to/images", body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

	resp, err := (&http.Client{Timeout: 60 * time.Second}).Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("Pixhost 返回非 200 状态码: %d, 响应: %s", resp.StatusCode, string(respBody))
	}
	var result struct {
		ShowURL string `json:"show_url"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", err
	}
	log.Printf("Pixhost 上传成功, URL: %s", result.ShowURL)
	return result.ShowURL, nil
}

// ======================= HTTP 处理器 =======================

func allTorrentsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSONResponse(w, r, http.StatusMethodNotAllowed, map[string]interface{}{"success": false, "message": "仅支持 POST 方法"})
		return
	}
	var req TorrentsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSONResponse(w, r, http.StatusBadRequest, map[string]interface{}{"success": false, "message": "无效的 JSON 请求体: " + err.Error()})
		return
	}
	if len(req.Downloaders) == 0 {
		writeJSONResponse(w, r, http.StatusOK, []NormalizedInfo{})
		return
	}

	var wg sync.WaitGroup
	resultsChan := make(chan []NormalizedTorrent, len(req.Downloaders))
	errChan := make(chan error, len(req.Downloaders))
	for _, config := range req.Downloaders {
		wg.Add(1)
		go fetchTorrentsForDownloader(&wg, config, req.IncludeComment, req.IncludeTrackers, resultsChan, errChan)
	}
	wg.Wait()
	close(resultsChan)
	close(errChan)

	allTorrentsRaw := make([]NormalizedTorrent, 0)
	for result := range resultsChan {
		allTorrentsRaw = append(allTorrentsRaw, result...)
	}
	for err := range errChan {
		log.Printf("错误: %v", err)
	}

	normalizedInfos := make([]NormalizedInfo, 0, len(allTorrentsRaw))
	for _, rawTorrent := range allTorrentsRaw {
		normalizedInfos = append(normalizedInfos, toNormalizedInfo(rawTorrent))
	}
	writeJSONResponse(w, r, http.StatusOK, normalizedInfos)
}

func statsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSONResponse(w, r, http.StatusMethodNotAllowed, map[string]interface{}{"success": false, "message": "仅支持 POST 方法"})
		return
	}
	var configs []DownloaderConfig
	if err := json.NewDecoder(r.Body).Decode(&configs); err != nil {
		writeJSONResponse(w, r, http.StatusBadRequest, map[string]interface{}{"success": false, "message": "无效的 JSON 请求体: " + err.Error()})
		return
	}
	if len(configs) == 0 {
		writeJSONResponse(w, r, http.StatusOK, []ServerStats{})
		return
	}

	var wg sync.WaitGroup
	resultsChan := make(chan ServerStats, len(configs))
	errChan := make(chan error, len(configs))
	for _, config := range configs {
		wg.Add(1)
		go fetchServerStatsForDownloader(&wg, config, resultsChan, errChan)
	}
	wg.Wait()
	close(resultsChan)
	close(errChan)

	allStats := make([]ServerStats, 0)
	for stats := range resultsChan {
		allStats = append(allStats, stats)
	}
	for err := range errChan {
		log.Printf("错误: %v", err)
	}
	writeJSONResponse(w, r, http.StatusOK, allStats)
}

func screenshotHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSONResponse(w, r, http.StatusMethodNotAllowed, ScreenshotResponse{Success: false, Message: "仅支持 POST 方法"})
		return
	}
	var reqData ScreenshotRequest
	if err := json.NewDecoder(r.Body).Decode(&reqData); err != nil {
		writeJSONResponse(w, r, http.StatusBadRequest, ScreenshotResponse{Success: false, Message: "无效的 JSON 请求体: " + err.Error()})
		return
	}
	videoPath := reqData.RemotePath
	if videoPath == "" {
		writeJSONResponse(w, r, http.StatusBadRequest, ScreenshotResponse{Success: false, Message: "remote_path 不能为空"})
		return
	}

	duration, err := getVideoDuration(videoPath)
	if err != nil {
		writeJSONResponse(w, r, http.StatusInternalServerError, ScreenshotResponse{Success: false, Message: "获取视频时长失败: " + err.Error()})
		return
	}

	subtitleIndex, err := findFirstSubtitleStream(videoPath)
	if err != nil {
		log.Printf("警告: 探测字幕流时发生错误: %v", err)
		subtitleIndex = -1
	}

	tempDir, err := os.MkdirTemp("", "screenshots-*")
	if err != nil {
		writeJSONResponse(w, r, http.StatusInternalServerError, ScreenshotResponse{Success: false, Message: "创建临时目录失败: " + err.Error()})
		return
	}
	defer os.RemoveAll(tempDir)

	screenshotPoints := []float64{0.20, 0.35, 0.65}
	var uploadedURLs []string
	var wg sync.WaitGroup
	var mu sync.Mutex
	errChan := make(chan error, len(screenshotPoints))

	for i, point := range screenshotPoints {
		wg.Add(1)
		go func(i int, point float64) {
			defer wg.Done()
			screenshotPath := filepath.Join(tempDir, fmt.Sprintf("ss_%d.jpg", i+1))
			if err := takeScreenshot(videoPath, screenshotPath, duration*point, subtitleIndex); err != nil {
				errChan <- fmt.Errorf("第 %d 张图截图失败: %v", i+1, err)
				return
			}
			showURL, err := uploadToPixhost(screenshotPath)
			if err != nil {
				errChan <- fmt.Errorf("第 %d 张图上传失败: %v", i+1, err)
				return
			}
			directURL := strings.Replace(showURL, "https://pixhost.to/show/", "https://img1.pixhost.to/images/", 1)
			mu.Lock()
			uploadedURLs = append(uploadedURLs, directURL)
			mu.Unlock()
		}(i, point)
	}
	wg.Wait()
	close(errChan)

	var errors []string
	for err := range errChan {
		errors = append(errors, err.Error())
	}
	if len(errors) > 0 {
		writeJSONResponse(w, r, http.StatusInternalServerError, ScreenshotResponse{Success: false, Message: "处理截图时发生错误: " + strings.Join(errors, "; ")})
		return
	}

	var bbcodeBuilder strings.Builder
	for _, url := range uploadedURLs {
		bbcodeBuilder.WriteString(fmt.Sprintf("[img]%s[/img]\n", url))
	}

	writeJSONResponse(w, r, http.StatusOK, ScreenshotResponse{
		Success: true, Message: "截图上传成功", BBCode: strings.TrimSpace(bbcodeBuilder.String()),
	})
}

func mediainfoHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSONResponse(w, r, http.StatusMethodNotAllowed, MediaInfoResponse{Success: false, Message: "仅支持 POST 方法"})
		return
	}
	var reqData MediaInfoRequest
	if err := json.NewDecoder(r.Body).Decode(&reqData); err != nil {
		writeJSONResponse(w, r, http.StatusBadRequest, MediaInfoResponse{Success: false, Message: "无效的 JSON 请求体: " + err.Error()})
		return
	}
	videoPath := reqData.RemotePath
	if videoPath == "" {
		writeJSONResponse(w, r, http.StatusBadRequest, MediaInfoResponse{Success: false, Message: "remote_path 不能为空"})
		return
	}

	log.Printf("正在获取 MediaInfo: %s", videoPath)
	mediaInfoText, err := executeCommand("mediainfo", "--Output=text", videoPath)
	if err != nil {
		writeJSONResponse(w, r, http.StatusInternalServerError, MediaInfoResponse{Success: false, Message: "获取 MediaInfo 失败: " + err.Error()})
		return
	}

	writeJSONResponse(w, r, http.StatusOK, MediaInfoResponse{
		Success: true, Message: "MediaInfo 获取成功", MediaInfoText: strings.TrimSpace(mediaInfoText),
	})
}

// ======================= 主函数 =======================

func main() {
	http.HandleFunc("/api/torrents/all", allTorrentsHandler)
	http.HandleFunc("/api/stats/server", statsHandler)
	http.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSONResponse(w, r, http.StatusOK, map[string]string{"status": "ok", "message": "qBittorrent代理服务运行正常"})
	})
	http.HandleFunc("/api/media/screenshot", screenshotHandler)
	http.HandleFunc("/api/media/mediainfo", mediainfoHandler)

	log.Println("增强版qBittorrent代理服务器正在启动...")
	log.Println("API端点:")
	log.Println("  POST /api/torrents/all - 获取种子信息")
	log.Println("  POST /api/stats/server - 获取服务器统计")
	log.Println("  GET  /api/health      - 健康检查")
	log.Println("  POST /api/media/screenshot - 远程截图并上传图床")
	log.Println("  POST /api/media/mediainfo  - 远程获取MediaInfo")
	log.Println("监听端口: 9090")

	if err := http.ListenAndServe(":9090", nil); err != nil {
		log.Fatalf("启动服务器失败: %v", err)
	}
}
