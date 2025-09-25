// proxy.go (最终修复和简化版)
package main

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"image"
	"image/jpeg"

	// [核心修复] 导入PNG解码器，解决 "unknown format" 问题
	_ "image/png"
	"io"
	"log"
	"math/rand"
	"mime/multipart"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/superturkey650/go-qbittorrent/qbt"
)

// ======================= 结构体定义 (无变动) =======================

type DownloaderConfig struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	Host     string `json:"host"`
	Username string `json:"username"`
	Password string `json:"password"`
}
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
type NormalizedInfo struct {
	Hash         string              `json:"hash"`
	Name         string              `json:"name"`
	Size         int64               `json:"size"`
	Progress     float64             `json:"progress"`
	State        string              `json:"state"`
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
type SubtitleEvent struct {
	StartTime float64
	EndTime   float64
}

// ======================= 辅助函数 (无变动) =======================

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

// ======================= 核心业务逻辑 (无变动) =======================

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

// ======================= 媒体处理辅助函数 (无变动) =======================

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
func buildReadIntervals(duration float64) string {
	probePoints := []float64{0.2, 0.4, 0.6, 0.8}
	probeDuration := 60.0
	var intervals []string
	for _, point := range probePoints {
		startTime := duration * point
		endTime := startTime + probeDuration
		if endTime > duration {
			endTime = duration
		}
		intervals = append(intervals, fmt.Sprintf("%.2f%%%.2f", startTime, endTime))
	}
	intervalArg := strings.Join(intervals, ",")
	log.Printf("   🚀 将只扫描以下时间段来寻找字幕: %s", intervalArg)
	return intervalArg
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
func findFirstSubtitleStream(videoPath string) (int, string, error) {
	log.Printf("正在为视频 '%s' 探测字幕流...", filepath.Base(videoPath))
	args := []string{"-v", "quiet", "-print_format", "json", "-show_entries", "stream=index,codec_name,codec_type,disposition", "-select_streams", "s", videoPath}
	output, err := executeCommand("ffprobe", args...)
	if err != nil {
		return -1, "", fmt.Errorf("ffprobe 探测字幕失败: %v", err)
	}
	var probeResult struct {
		Streams []struct {
			Index       int    `json:"index"`
			CodecName   string `json:"codec_name"`
			Disposition struct {
				Comment         int `json:"comment"`
				HearingImpaired int `json:"hearing_impaired"`
				VisualImpaired  int `json:"visual_impaired"`
			} `json:"disposition"`
		} `json:"streams"`
	}
	if err := json.Unmarshal([]byte(output), &probeResult); err != nil {
		log.Printf("警告: 解析 ffprobe 的字幕 JSON 输出失败: %v。将不带字幕截图。", err)
		return -1, "", nil
	}
	if len(probeResult.Streams) == 0 {
		log.Printf("视频中未发现内嵌字幕流。")
		return -1, "", nil
	}
	type SubtitleChoice struct {
		Index     int
		CodecName string
	}
	var bestASS, bestSRT, bestPGS SubtitleChoice
	bestASS.Index, bestSRT.Index, bestPGS.Index = -1, -1, -1
	for _, stream := range probeResult.Streams {
		isNormal := stream.Disposition.Comment == 0 && stream.Disposition.HearingImpaired == 0 && stream.Disposition.VisualImpaired == 0
		if isNormal {
			switch stream.CodecName {
			case "ass":
				if bestASS.Index == -1 {
					bestASS = SubtitleChoice{Index: stream.Index, CodecName: stream.CodecName}
				}
			case "subrip":
				if bestSRT.Index == -1 {
					bestSRT = SubtitleChoice{Index: stream.Index, CodecName: stream.CodecName}
				}
			case "hdmv_pgs_subtitle":
				if bestPGS.Index == -1 {
					bestPGS = SubtitleChoice{Index: stream.Index, CodecName: stream.CodecName}
				}
			}
		}
	}
	if bestASS.Index != -1 {
		log.Printf("   ✅ 找到最优字幕流 (ASS)，流索引: %d, 格式: %s", bestASS.Index, bestASS.CodecName)
		return bestASS.Index, bestASS.CodecName, nil
	}
	if bestSRT.Index != -1 {
		log.Printf("   ✅ 找到可用字幕流 (SRT)，流索引: %d, 格式: %s", bestSRT.Index, bestSRT.CodecName)
		return bestSRT.Index, bestSRT.CodecName, nil
	}
	if bestPGS.Index != -1 {
		log.Printf("   ✅ 找到可用字幕流 (PGS)，流索引: %d, 格式: %s", bestPGS.Index, bestPGS.CodecName)
		return bestPGS.Index, bestPGS.CodecName, nil
	}
	firstStream := probeResult.Streams[0]
	log.Printf("   ⚠️ 未找到任何“正常”字幕流，将使用第一个字幕流 (索引: %d, 格式: %s)", firstStream.Index, firstStream.CodecName)
	return firstStream.Index, firstStream.CodecName, nil
}
func takeScreenshot(videoPath, outputPath string, timePoint float64, subtitleStreamIndex int) error {
	log.Printf("正在使用 mpv 截图 (时间点: %.2fs) -> %s", timePoint, outputPath)
	args := []string{
		"--no-audio",
		fmt.Sprintf("--start=%.2f", timePoint),
		"--frames=1",

		// --- HDR 色调映射参数 ---
		// 指定输出为标准的sRGB色彩空间，这是所有SDR图片的基础
		"--target-trc=srgb",
		// 使用 'hable' 算法进行色调映射，它能在保留高光和阴影细节方面取得良好平衡
		"--tone-mapping=hable",

		fmt.Sprintf("--o=%s", outputPath),
		videoPath,
	}
	_, err := executeCommand("mpv", args...)
	if err != nil {
		log.Printf("mpv 截图失败，最终执行的命令: mpv %s", strings.Join(args, " "))
		return fmt.Errorf("mpv 截图失败: %v", err)
	}
	log.Printf("   ✅ mpv 截图成功 -> %s", outputPath)
	return nil
}
func convertPngToJpeg(sourcePath, destPath string) error {
	pngFile, err := os.Open(sourcePath)
	if err != nil {
		return fmt.Errorf("无法打开中间PNG文件 '%s': %v", filepath.Base(sourcePath), err)
	}
	defer pngFile.Close()

	img, _, err := image.Decode(pngFile)
	if err != nil {
		return fmt.Errorf("无法解码PNG文件 '%s': %v", filepath.Base(sourcePath), err)
	}

	jpegFile, err := os.Create(destPath)
	if err != nil {
		return fmt.Errorf("无法创建最终JPEG文件 '%s': %v", filepath.Base(destPath), err)
	}
	defer jpegFile.Close()

	options := &jpeg.Options{Quality: 85}
	if err := jpeg.Encode(jpegFile, img, options); err != nil {
		return fmt.Errorf("无法将图片编码为JPEG格式: %v", err)
	}

	log.Printf("   -> JPEG 转换和压缩成功 (质量: %d) -> %s", options.Quality, filepath.Base(destPath))
	return nil
}
func uploadToPixhost(imagePath string) (string, error) {
	const maxRetries = 3
	var lastErr error
	for attempt := 1; attempt <= maxRetries; attempt++ {
		log.Printf("准备上传图片到 Pixhost (第 %d/%d 次尝试): %s", attempt, maxRetries, imagePath)
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
		client := &http.Client{Timeout: 60 * time.Second}
		resp, err := client.Do(req)
		if err != nil {
			lastErr = fmt.Errorf("上传请求失败: %w", err)
			log.Printf("   -> 第 %d 次尝试失败: %v", attempt, lastErr)
			if attempt < maxRetries {
				time.Sleep(time.Duration(attempt) * 2 * time.Second)
			}
			continue
		}
		defer resp.Body.Close()
		if resp.StatusCode == http.StatusOK {
			var result struct {
				ShowURL string `json:"show_url"`
			}
			if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
				lastErr = fmt.Errorf("解析成功响应失败: %w", err)
				log.Printf("   -> 第 %d 次尝试失败: %v", attempt, lastErr)
			} else {
				log.Printf("   ✅ Pixhost 上传成功, URL: %s", result.ShowURL)
				return result.ShowURL, nil
			}
		} else {
			respBody, _ := io.ReadAll(resp.Body)
			lastErr = fmt.Errorf("Pixhost 返回非 200 状态码: %d, 响应: %s", resp.StatusCode, string(respBody))
			log.Printf("   -> 第 %d 次尝试失败: %v", attempt, lastErr)
		}
		if attempt < maxRetries {
			time.Sleep(time.Duration(attempt) * 2 * time.Second)
		}
	}
	return "", fmt.Errorf("经过 %d 次尝试后上传失败: %w", maxRetries, lastErr)
}
func findSubtitleEvents(videoPath string, subtitleStreamIndex int, duration float64) ([]SubtitleEvent, error) {
	log.Printf("正在为视频 '%s' (字幕流索引 %d) 智能提取字幕时间点 (快速扫描模式)...", filepath.Base(videoPath), subtitleStreamIndex)
	if subtitleStreamIndex < 0 {
		return nil, fmt.Errorf("无效的字幕流索引")
	}
	readIntervalsArg := buildReadIntervals(duration)
	args := []string{"-v", "quiet", "-read_intervals", readIntervalsArg, "-print_format", "json", "-show_packets", "-select_streams", fmt.Sprintf("%d", subtitleStreamIndex), videoPath}
	output, err := executeCommand("ffprobe", args...)
	if err != nil {
		return nil, fmt.Errorf("ffprobe 提取字幕数据包失败: %v", err)
	}
	jsonStartIndex := strings.Index(output, "{")
	if jsonStartIndex == -1 {
		return nil, fmt.Errorf("ffprobe 输出中未找到有效的JSON内容")
	}
	jsonOutput := output[jsonStartIndex:]
	var probeResult struct {
		Packets []struct {
			PtsTime      string `json:"pts_time"`
			DurationTime string `json:"duration_time"`
		} `json:"packets"`
	}
	if err := json.Unmarshal([]byte(jsonOutput), &probeResult); err != nil {
		return nil, fmt.Errorf("解析 ffprobe 的字幕JSON输出失败: %v", err)
	}
	var events []SubtitleEvent
	for _, packet := range probeResult.Packets {
		start, err1 := strconv.ParseFloat(packet.PtsTime, 64)
		duration, err2 := strconv.ParseFloat(packet.DurationTime, 64)
		if err1 == nil && err2 == nil && duration > 0.1 {
			end := start + duration
			events = append(events, SubtitleEvent{StartTime: start, EndTime: end})
		}
	}
	if len(events) == 0 {
		return nil, fmt.Errorf("未能在指定区间内提取到任何有效的时间事件")
	}
	log.Printf("   ✅ 成功从指定区间提取到 %d 条字幕事件。", len(events))
	return events, nil
}
func findSubtitleEventsForPGS(videoPath string, subtitleStreamIndex int, duration float64) ([]SubtitleEvent, error) {
	log.Printf("正在为视频 '%s' (PGS字幕流索引 %d) 智能提取显示时间段 (快速扫描模式)...", filepath.Base(videoPath), subtitleStreamIndex)
	if subtitleStreamIndex < 0 {
		return nil, fmt.Errorf("无效的字幕流索引")
	}
	readIntervalsArg := buildReadIntervals(duration)
	args := []string{"-v", "quiet", "-read_intervals", readIntervalsArg, "-print_format", "json", "-show_packets", "-select_streams", fmt.Sprintf("%d", subtitleStreamIndex), videoPath}
	output, err := executeCommand("ffprobe", args...)
	if err != nil {
		return nil, fmt.Errorf("ffprobe 提取PGS数据包失败: %v", err)
	}
	jsonStartIndex := strings.Index(output, "{")
	if jsonStartIndex == -1 {
		return nil, fmt.Errorf("ffprobe 输出中未找到有效的JSON内容")
	}
	jsonOutput := output[jsonStartIndex:]
	var probeResult struct {
		Packets []struct {
			PtsTime string `json:"pts_time"`
		} `json:"packets"`
	}
	if err := json.Unmarshal([]byte(jsonOutput), &probeResult); err != nil {
		return nil, fmt.Errorf("解析 ffprobe 的PGS JSON输出失败: %v", err)
	}
	if len(probeResult.Packets) < 2 {
		return nil, fmt.Errorf("PGS字幕数据包数量过少，无法配对")
	}
	var events []SubtitleEvent
	for i := 0; i < len(probeResult.Packets)-1; i += 2 {
		start, err1 := strconv.ParseFloat(probeResult.Packets[i].PtsTime, 64)
		end, err2 := strconv.ParseFloat(probeResult.Packets[i+1].PtsTime, 64)
		if err1 == nil && err2 == nil && end > start && (end-start) > 0.1 {
			events = append(events, SubtitleEvent{StartTime: start, EndTime: end})
		}
	}
	if len(events) == 0 {
		return nil, fmt.Errorf("未能从PGS字幕流的指定区间中提取到任何有效的显示时间段")
	}
	log.Printf("   ✅ 成功从指定区间提取到 %d 个PGS字幕显示时间段。", len(events))
	return events, nil
}
func findTargetVideoFile(path string) (string, error) {
	log.Printf("开始在路径 '%s' 中智能查找目标视频文件...", path)
	videoExtensions := map[string]bool{".mkv": true, ".mp4": true, ".ts": true, ".avi": true, ".wmv": true, ".mov": true, ".flv": true, ".m2ts": true}
	info, err := os.Stat(path)
	if os.IsNotExist(err) {
		return "", fmt.Errorf("提供的路径不存在: %s", path)
	}
	if err != nil {
		return "", fmt.Errorf("无法获取路径信息: %v", err)
	}
	if !info.IsDir() {
		if videoExtensions[strings.ToLower(filepath.Ext(path))] {
			log.Printf("路径直接指向一个视频文件，将使用: %s", path)
			return path, nil
		}
		return "", fmt.Errorf("路径是一个文件，但不是支持的视频格式: %s", path)
	}
	var videoFiles []string
	err = filepath.Walk(path, func(filePath string, fileInfo os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !fileInfo.IsDir() && videoExtensions[strings.ToLower(filepath.Ext(filePath))] {
			videoFiles = append(videoFiles, filePath)
		}
		return nil
	})
	if err != nil {
		return "", fmt.Errorf("遍历目录失败: %v", err)
	}
	if len(videoFiles) == 0 {
		return "", fmt.Errorf("在目录 '%s' 中未找到任何视频文件", path)
	}
	seriesPattern := regexp.MustCompile(`(?i)[\._\s-](S\d{1,2}E\d{1,3}|Season[\._\s-]?\d{1,2}|E\d{1,3})[\._\s-]`)
	isSeries := false
	for _, f := range videoFiles {
		if seriesPattern.MatchString(filepath.Base(f)) {
			isSeries = true
			break
		}
	}
	if isSeries {
		log.Printf("检测到剧集命名格式，将选择第一集。")
		sort.Strings(videoFiles)
		targetFile := videoFiles[0]
		log.Printf("已选择剧集文件: %s", targetFile)
		return targetFile, nil
	} else {
		log.Printf("未检测到剧集格式，将按电影处理（选择最大文件）。")
		var largestFile string
		var maxSize int64 = -1
		for _, f := range videoFiles {
			fileInfo, err := os.Stat(f)
			if err != nil {
				log.Printf("警告: 无法获取文件 '%s' 的大小: %v", f, err)
				continue
			}
			if fileInfo.Size() > maxSize {
				maxSize = fileInfo.Size()
				largestFile = f
			}
		}
		if largestFile == "" {
			return "", fmt.Errorf("无法确定最大的视频文件")
		}
		log.Printf("已选择最大文件 (%.2f GB): %s", float64(maxSize)/1024/1024/1024, largestFile)
		return largestFile, nil
	}
}

// ======================= HTTP 处理器 (核心修改在这里) =======================

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

// [重构版] screenshotHandler, 移除并发，改为顺序执行
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
	initialPath := reqData.RemotePath
	if initialPath == "" {
		writeJSONResponse(w, r, http.StatusBadRequest, ScreenshotResponse{Success: false, Message: "remote_path 不能为空"})
		return
	}

	videoPath, err := findTargetVideoFile(initialPath)
	if err != nil {
		writeJSONResponse(w, r, http.StatusBadRequest, ScreenshotResponse{Success: false, Message: err.Error()})
		return
	}

	duration, err := getVideoDuration(videoPath)
	if err != nil {
		writeJSONResponse(w, r, http.StatusInternalServerError, ScreenshotResponse{Success: false, Message: "获取视频时长失败: " + err.Error()})
		return
	}

	subtitleIndex, subtitleCodec, err := findFirstSubtitleStream(videoPath)
	if err != nil {
		log.Printf("警告: 探测字幕流时发生错误: %v", err)
		subtitleIndex = -1
	}

	// 智能选择截图时间点 (逻辑不变)
	screenshotPoints := make([]float64, 0, 5)
	var subtitleEvents []SubtitleEvent
	const numScreenshots = 5
	if subtitleIndex >= 0 {
		if subtitleCodec == "subrip" || subtitleCodec == "ass" {
			subtitleEvents, err = findSubtitleEvents(videoPath, subtitleIndex, duration)
		} else if subtitleCodec == "hdmv_pgs_subtitle" {
			subtitleEvents, err = findSubtitleEventsForPGS(videoPath, subtitleIndex, duration)
		} else {
			err = fmt.Errorf("不支持的字幕格式 '%s' 用于智能截图", subtitleCodec)
		}
	}
	if err == nil && subtitleEvents != nil && len(subtitleEvents) >= numScreenshots {
		log.Printf("智能截图模式启动：找到 %d 个有效字幕事件/时间段。", len(subtitleEvents))
		rand.Seed(time.Now().UnixNano())
		goldenStartTime := duration * 0.30
		goldenEndTime := duration * 0.80
		var goldenEvents []SubtitleEvent
		for _, event := range subtitleEvents {
			if event.StartTime >= goldenStartTime && event.EndTime <= goldenEndTime {
				goldenEvents = append(goldenEvents, event)
			}
		}
		log.Printf("   -> 在视频中部 (%.2fs - %.2fs) 找到 %d 个“黄金”字幕事件。", goldenStartTime, goldenEndTime, len(goldenEvents))
		targetEvents := goldenEvents
		if len(targetEvents) < numScreenshots {
			log.Printf("   -> “黄金”字幕数量不足，将从所有字幕事件中随机选择。")
			targetEvents = subtitleEvents
		}
		if len(targetEvents) > 0 {
			randomIndices := rand.Perm(len(targetEvents))
			count := 0
			for _, idx := range randomIndices {
				if count >= numScreenshots {
					break
				}
				event := targetEvents[idx]
				durationOfEvent := event.EndTime - event.StartTime
				randomOffset := durationOfEvent*0.1 + rand.Float64()*(durationOfEvent*0.8)
				randomPoint := event.StartTime + randomOffset
				screenshotPoints = append(screenshotPoints, randomPoint)
				log.Printf("   -> 选中时间段 [%.2fs - %.2fs], 随机截图点: %.2fs", event.StartTime, event.EndTime, randomPoint)
				count++
			}
		}
	}
	if len(screenshotPoints) < numScreenshots {
		if err != nil {
			log.Printf("警告: 智能截图失败，回退到按百分比截图。原因: %v", err)
		} else {
			log.Printf("警告: 有效字幕数量不足，回退到按百分比截图。")
		}
		percentages := []float64{0.15, 0.30, 0.50, 0.70, 0.85}
		screenshotPoints = make([]float64, 0, len(percentages))
		for _, p := range percentages {
			screenshotPoints = append(screenshotPoints, duration*p)
		}
	}

	tempDir, err := os.MkdirTemp("", "screenshots-*")
	if err != nil {
		writeJSONResponse(w, r, http.StatusInternalServerError, ScreenshotResponse{Success: false, Message: "创建临时目录失败: " + err.Error()})
		return
	}
	defer os.RemoveAll(tempDir)

	var uploadedURLs []string

	// [核心修改] 改为简单的顺序for循环
	for i, point := range screenshotPoints {
		log.Printf("开始处理第 %d/%d 张截图...", i+1, len(screenshotPoints))

		timestamp := time.Now().UnixNano()
		intermediatePngPath := filepath.Join(tempDir, fmt.Sprintf("ss_%d_%d_temp.png", i+1, timestamp))
		finalJpegPath := filepath.Join(tempDir, fmt.Sprintf("ss_%d_%d.jpg", i+1, timestamp))

		// 步骤1: 截图
		if err := takeScreenshot(videoPath, intermediatePngPath, point, subtitleIndex); err != nil {
			errMsg := fmt.Sprintf("第 %d 张图截图失败: %v", i+1, err)
			log.Println(errMsg)
			writeJSONResponse(w, r, http.StatusInternalServerError, ScreenshotResponse{Success: false, Message: errMsg})
			return // 失败则立即停止并返回错误
		}

		// 步骤2: 转换格式
		if err := convertPngToJpeg(intermediatePngPath, finalJpegPath); err != nil {
			errMsg := fmt.Sprintf("第 %d 张图转换格式失败: %v", i+1, err)
			log.Println(errMsg)
			writeJSONResponse(w, r, http.StatusInternalServerError, ScreenshotResponse{Success: false, Message: errMsg})
			return // 失败则立即停止并返回错误
		}

		// 步骤3: 上传
		showURL, err := uploadToPixhost(finalJpegPath)
		if err != nil {
			errMsg := fmt.Sprintf("第 %d 张图上传失败: %v", i+1, err)
			log.Println(errMsg)
			writeJSONResponse(w, r, http.StatusInternalServerError, ScreenshotResponse{Success: false, Message: errMsg})
			return // 失败则立即停止并返回错误
		}

		directURL := strings.Replace(showURL, "https://pixhost.to/show/", "https://img1.pixhost.to/images/", 1)
		uploadedURLs = append(uploadedURLs, directURL)
		log.Printf("第 %d/%d 张截图处理成功。", i+1, len(screenshotPoints))
	}

	if len(uploadedURLs) < numScreenshots {
		msg := fmt.Sprintf("处理完成，但成功上传的图片数量 (%d) 少于预期 (%d)", len(uploadedURLs), numScreenshots)
		writeJSONResponse(w, r, http.StatusInternalServerError, ScreenshotResponse{Success: false, Message: msg})
		return
	}

	sort.Strings(uploadedURLs)
	var bbcodeBuilder strings.Builder
	for _, url := range uploadedURLs {
		bbcodeBuilder.WriteString(fmt.Sprintf("[img]%s[/img]\n", url))
	}

	writeJSONResponse(w, r, http.StatusOK, ScreenshotResponse{
		Success: true, Message: "所有截图均已成功上传", BBCode: strings.TrimSpace(bbcodeBuilder.String()),
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
	initialPath := reqData.RemotePath
	if initialPath == "" {
		writeJSONResponse(w, r, http.StatusBadRequest, MediaInfoResponse{Success: false, Message: "remote_path 不能为空"})
		return
	}
	videoPath, err := findTargetVideoFile(initialPath)
	if err != nil {
		writeJSONResponse(w, r, http.StatusBadRequest, MediaInfoResponse{Success: false, Message: err.Error()})
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

// ======================= 主函数 (无变动) =======================

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
