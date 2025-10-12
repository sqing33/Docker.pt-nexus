package main

import (
	"bufio"
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// 种子处理记录结构
type SeedRecord struct {
	BatchID     string  `json:"batch_id"`
	TorrentID   string  `json:"torrent_id"`
	Title       string  `json:"title,omitempty"`
	SourceSite  string  `json:"source_site"`
	TargetSite  string  `json:"target_site"`
	VideoSizeGB float64 `json:"video_size_gb,omitempty"`
	Status      string  `json:"status"`
	SuccessURL  string  `json:"success_url,omitempty"`
	ErrorDetail string  `json:"error_detail,omitempty"`
}

type RecordResponse struct {
	Success bool         `json:"success"`
	Records []SeedRecord `json:"records,omitempty"`
	Error   string       `json:"error,omitempty"`
}

// 保留简化的日志结构用于控制台输出
type LogEntry struct {
	Timestamp string `json:"timestamp"`
	Message   string `json:"message"`
	Level     string `json:"level"`
}

// 全局变量
var (
	logFile        *os.File
	logMutex       sync.RWMutex
	logEntries     []LogEntry
	maxLogLines    = 1000 // 最大保存的日志行数
	currentBatchID string // 当前批次ID
)

// 简单的请求和响应结构
type BatchRequest struct {
	TargetSiteName string         `json:"target_site_name"`
	Seeds          []SeedInfo     `json:"seeds"`
	FilterOptions  *FilterOptions `json:"filter_options,omitempty"`
}

type FilterOptions struct {
	EnableSizeFilter bool `json:"enable_size_filter"`
}

type SeedInfo struct {
	Hash        string  `json:"hash"`
	TorrentID   string  `json:"torrent_id"`
	SiteName    string  `json:"site_name"`
	Nickname    string  `json:"nickname"`
	VideoSizeGB float64 `json:"video_size_gb,omitempty"` // 添加视频大小字段
}

type BatchResponse struct {
	Success bool       `json:"success"`
	Message string     `json:"message"`
	Data    *BatchData `json:"data,omitempty"`
	Error   string     `json:"error,omitempty"`
}

type BatchData struct {
	TargetSiteName string       `json:"target_site_name"`
	SeedsProcessed int          `json:"seeds_processed"`
	SeedsFailed    int          `json:"seeds_failed"`
	SeedsFiltered  int          `json:"seeds_filtered"`
	ProcessedSeeds []SeedResult `json:"processed_seeds"`
	FailedSeeds    []SeedResult `json:"failed_seeds"`
	FilteredSeeds  []SeedResult `json:"filtered_seeds"`
	FilterStats    FilterStats  `json:"filter_stats"`
}

type FilterStats struct {
	TotalSeeds    int     `json:"total_seeds"`
	SizeFiltered  int     `json:"size_filtered"`
	AverageSize   float64 `json:"average_size_gb"`
	LargestVideo  string  `json:"largest_video"`
	SmallestVideo string  `json:"smallest_video"`
}

type SeedResult struct {
	TorrentID    string  `json:"torrent_id"`
	Title        string  `json:"title,omitempty"`
	Status       string  `json:"status"`
	URL          string  `json:"url,omitempty"`
	Error        string  `json:"error,omitempty"`
	VideoSizeGB  float64 `json:"video_size_gb,omitempty"`
	FilterReason string  `json:"filter_reason,omitempty"`
}

// Torrent文件解析结构
type TorrentInfo struct {
	Name   string        `json:"name"`
	Files  []TorrentFile `json:"files,omitempty"`
	Length int64         `json:"length,omitempty"`
}

type TorrentFile struct {
	Path   []string `json:"path"`
	Length int64    `json:"length"`
}

type Torrent struct {
	Info TorrentInfo `json:"info"`
}

// Bencode解析器
type BencodeParser struct {
	data []byte
	pos  int
}

// 配置
var (
	coreAPIURL     = getEnv("CORE_API_URL", "http://localhost:5274")
	port           = getEnv("PORT", "5275")
	tempDir        = getEnv("TEMP_DIR", "/app/data/tmp")
	// tempDir        = getEnv("TEMP_DIR", "/app/Code/Dockerfile/Docker.pt-nexus/server/data/tmp")
	internalSecret = getEnv("INTERNAL_SECRET", "pt-nexus-secret-key") // 共享密钥，用于生成动态token
)

// 全局站点请求频率控制
var (
	siteLastRequestTime = make(map[string]time.Time)
	siteRequestMutex    sync.Mutex
	minRequestInterval  = 5 * time.Second
)

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// 初始化日志系统
func initLogging() error {
	// 创建日志文件
	logPath := filepath.Join(tempDir, "batch-enhancer.log")
	var err error
	logFile, err = os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return fmt.Errorf("无法创建日志文件: %v", err)
	}

	// 设置log包的输出到文件和控制台
	multiWriter := io.MultiWriter(os.Stdout, logFile)
	log.SetOutput(multiWriter)

	// 从现有日志文件中读取日志条目
	loadExistingLogs(logPath)

	return nil
}

// 从文件加载现有的日志条目
func loadExistingLogs(logPath string) {
	file, err := os.Open(logPath)
	if err != nil {
		return // 文件不存在或无法打开
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		logEntry := parseLogLine(line)
		if logEntry != nil {
			logMutex.Lock()
			logEntries = append(logEntries, *logEntry)
			// 保持日志条目数量在限制内
			if len(logEntries) > maxLogLines {
				logEntries = logEntries[len(logEntries)-maxLogLines:]
			}
			logMutex.Unlock()
		}
	}
}

// 解析日志行
func parseLogLine(line string) *LogEntry {
	// 简单的日志行解析，格式: 2024/01/01 12:00:00 message
	if len(line) < 20 {
		return nil
	}

	// 提取时间戳部分 (前19个字符)
	timestampStr := line[:19]
	message := strings.TrimSpace(line[20:])

	// 解析时间
	timestamp, err := time.Parse("2006/01/02 15:04:05", timestampStr)
	if err != nil {
		// 如果解析失败，使用当前时间
		timestamp = time.Now()
	}

	// 根据消息内容推断日志级别
	level := "info"
	messageLower := strings.ToLower(message)
	if strings.Contains(messageLower, "错误") || strings.Contains(messageLower, "失败") || strings.Contains(messageLower, "error") {
		level = "error"
	} else if strings.Contains(messageLower, "警告") || strings.Contains(messageLower, "warning") {
		level = "warning"
	} else if strings.Contains(messageLower, "成功") || strings.Contains(messageLower, "完成") {
		level = "success"
	}

	return &LogEntry{
		Timestamp: timestamp.Format(time.RFC3339),
		Message:   message,
		Level:     level,
	}
}

// 记录日志到控制台和文件
func logWithLevel(level, format string, args ...interface{}) {
	message := fmt.Sprintf(format, args...)

	// 记录到标准输出和文件
	log.Print(message)

	// 同时保存到内存中供API查询（作为备份）
	entry := LogEntry{
		Timestamp: time.Now().Format(time.RFC3339),
		Message:   message,
		Level:     level,
	}

	logMutex.Lock()
	logEntries = append(logEntries, entry)
	// 保持日志条目数量在限制内
	if len(logEntries) > maxLogLines {
		logEntries = logEntries[1:] // 删除最早的条目
	}
	logMutex.Unlock()
}

// 便捷的日志记录函数
func logInfo(format string, args ...interface{}) {
	logWithLevel("info", format, args...)
}

func logWarning(format string, args ...interface{}) {
	logWithLevel("warning", format, args...)
}

func logError(format string, args ...interface{}) {
	logWithLevel("error", format, args...)
}

func logSuccess(format string, args ...interface{}) {
	logWithLevel("success", format, args...)
}

// 站点请求频率控制函数
func waitForSiteRequest(siteName string) {
	siteRequestMutex.Lock()
	defer siteRequestMutex.Unlock()

	lastTime, exists := siteLastRequestTime[siteName]
	if exists {
		elapsed := time.Since(lastTime)
		if elapsed < minRequestInterval {
			waitTime := minRequestInterval - elapsed
			logInfo("⏰ 站点 %s 请求间隔控制，等待 %v", siteName, waitTime)
			time.Sleep(waitTime)
		}
	}

	siteLastRequestTime[siteName] = time.Now()
}

// 生成动态内部认证token
func generateInternalToken() string {
	// 使用当前时间的小时数作为时间窗口（每小时更新一次）
	timestamp := time.Now().Unix() / 3600 // 小时级别的时间戳

	// 使用HMAC-SHA256生成签名
	h := hmac.New(sha256.New, []byte(internalSecret))
	h.Write([]byte(fmt.Sprintf("pt-nexus-internal-%d", timestamp)))
	signature := hex.EncodeToString(h.Sum(nil))

	// 返回前16位作为token（足够安全且不会太长）
	return signature[:16]
}

// 记录种子处理结果到数据库
func recordSeedResult(record SeedRecord) error {
	// 调用Python API记录种子处理结果
	recordData := map[string]interface{}{
		"batch_id":      record.BatchID,
		"title":         record.Title,
		"torrent_id":    record.TorrentID,
		"source_site":   record.SourceSite,
		"target_site":   record.TargetSite,
		"video_size_gb": record.VideoSizeGB,
		"status":        record.Status,
		"success_url":   record.SuccessURL,
		"error_detail":  record.ErrorDetail,
	}

	resp, err := callPythonAPI("/api/batch-enhance/records", recordData)
	if err != nil {
		return fmt.Errorf("记录种子处理结果到数据库失败: %v", err)
	}

	if success, ok := resp["success"].(bool); !ok || !success {
		return fmt.Errorf("数据库返回记录失败: %v", resp["error"])
	}

	return nil
}

// 生成批次ID
func generateBatchID() string {
	return fmt.Sprintf("batch_%d_%d", time.Now().Unix(), time.Now().Nanosecond()%1000000)
}

// Bencode解析器方法
func (p *BencodeParser) parseValue() (interface{}, error) {
	if p.pos >= len(p.data) {
		return nil, fmt.Errorf("unexpected end of data")
	}

	switch p.data[p.pos] {
	case 'd':
		return p.parseDict()
	case 'l':
		return p.parseList()
	case 'i':
		return p.parseInteger()
	default:
		if p.data[p.pos] >= '0' && p.data[p.pos] <= '9' {
			return p.parseString()
		}
		return nil, fmt.Errorf("invalid bencode data at position %d", p.pos)
	}
}

func (p *BencodeParser) parseString() (string, error) {
	start := p.pos
	for p.pos < len(p.data) && p.data[p.pos] != ':' {
		p.pos++
	}
	if p.pos >= len(p.data) {
		return "", fmt.Errorf("invalid string format")
	}

	lengthStr := string(p.data[start:p.pos])
	length, err := strconv.Atoi(lengthStr)
	if err != nil {
		return "", err
	}

	p.pos++ // skip ':'
	if p.pos+length > len(p.data) {
		return "", fmt.Errorf("string length exceeds data")
	}

	result := string(p.data[p.pos : p.pos+length])
	p.pos += length
	return result, nil
}

func (p *BencodeParser) parseInteger() (int64, error) {
	p.pos++ // skip 'i'
	start := p.pos
	for p.pos < len(p.data) && p.data[p.pos] != 'e' {
		p.pos++
	}
	if p.pos >= len(p.data) {
		return 0, fmt.Errorf("invalid integer format")
	}

	numStr := string(p.data[start:p.pos])
	p.pos++ // skip 'e'
	return strconv.ParseInt(numStr, 10, 64)
}

func (p *BencodeParser) parseList() ([]interface{}, error) {
	p.pos++ // skip 'l'
	var result []interface{}

	for p.pos < len(p.data) && p.data[p.pos] != 'e' {
		value, err := p.parseValue()
		if err != nil {
			return nil, err
		}
		result = append(result, value)
	}

	if p.pos >= len(p.data) {
		return nil, fmt.Errorf("unterminated list")
	}
	p.pos++ // skip 'e'
	return result, nil
}

func (p *BencodeParser) parseDict() (map[string]interface{}, error) {
	p.pos++ // skip 'd'
	result := make(map[string]interface{})

	for p.pos < len(p.data) && p.data[p.pos] != 'e' {
		key, err := p.parseString()
		if err != nil {
			return nil, err
		}

		value, err := p.parseValue()
		if err != nil {
			return nil, err
		}

		result[key] = value
	}

	if p.pos >= len(p.data) {
		return nil, fmt.Errorf("unterminated dictionary")
	}
	p.pos++ // skip 'e'
	return result, nil
}

// 解析torrent文件
func parseTorrentFile(filename string) (*Torrent, error) {
	data, err := os.ReadFile(filename)
	if err != nil {
		return nil, err
	}

	parser := &BencodeParser{data: data, pos: 0}
	root, err := parser.parseDict()
	if err != nil {
		return nil, err
	}

	// 提取info字段
	infoRaw, ok := root["info"].(map[string]interface{})
	if !ok {
		return nil, fmt.Errorf("missing or invalid info field")
	}

	torrent := &Torrent{}

	// 解析name
	if name, ok := infoRaw["name"].(string); ok {
		torrent.Info.Name = name
	}

	// 检查是否为多文件torrent
	if filesRaw, ok := infoRaw["files"].([]interface{}); ok {
		// 多文件torrent
		for _, fileRaw := range filesRaw {
			if fileDict, ok := fileRaw.(map[string]interface{}); ok {
				file := TorrentFile{}

				if length, ok := fileDict["length"].(int64); ok {
					file.Length = length
				}

				if pathList, ok := fileDict["path"].([]interface{}); ok {
					for _, pathComponent := range pathList {
						if pathStr, ok := pathComponent.(string); ok {
							file.Path = append(file.Path, pathStr)
						}
					}
				}

				torrent.Info.Files = append(torrent.Info.Files, file)
			}
		}
	} else if length, ok := infoRaw["length"].(int64); ok {
		// 单文件torrent
		torrent.Info.Length = length
	}

	return torrent, nil
}

// 检查是否为视频文件
func isVideoFile(filename string) bool {
	ext := strings.ToLower(filepath.Ext(filename))
	videoExts := map[string]bool{
		".mp4": true, ".mkv": true, ".avi": true, ".mov": true,
		".wmv": true, ".flv": true, ".webm": true, ".m4v": true,
		".mpg": true, ".mpeg": true, ".ts": true, ".m2ts": true,
		".vob": true, ".iso": true,
	}
	return videoExts[ext]
}

// 从torrent文件中提取视频文件大小
func extractVideoSizeFromTorrent(torrentPath string) (float64, string, error) {
	torrent, err := parseTorrentFile(torrentPath)
	if err != nil {
		return 0, "", fmt.Errorf("解析torrent文件失败: %v", err)
	}

	var totalVideoSize int64
	var totalAllSize int64
	var largestVideoFile string
	var largestVideoSize int64
	var videoFileCount int
	var allFileCount int

	if len(torrent.Info.Files) > 0 {
		// 多文件torrent
		for _, file := range torrent.Info.Files {
			allFileCount++
			totalAllSize += file.Length

			if len(file.Path) > 0 {
				filename := file.Path[len(file.Path)-1] // 获取文件名

				if isVideoFile(filename) {
					videoFileCount++
					totalVideoSize += file.Length
					if file.Length > largestVideoSize {
						largestVideoSize = file.Length
						largestVideoFile = filename
					}
				}
			}
		}
	} else if torrent.Info.Length > 0 {
		// 单文件torrent
		allFileCount = 1
		totalAllSize = torrent.Info.Length

		if isVideoFile(torrent.Info.Name) {
			videoFileCount = 1
			totalVideoSize = torrent.Info.Length
			largestVideoFile = torrent.Info.Name
		}
	}

	// 只输出简要统计信息
	totalVideoSizeGB := float64(totalVideoSize) / (1024 * 1024 * 1024)
	logInfo("     📊 解析结果: %s, 视频大小 %.2fGB", torrent.Info.Name, totalVideoSizeGB)

	if totalVideoSize == 0 {
		return 0, "", fmt.Errorf("未找到视频文件")
	}

	// 转换为GB
	sizeGB := float64(totalVideoSize) / (1024 * 1024 * 1024)
	return sizeGB, largestVideoFile, nil
}

// 查找torrent文件
func findTorrentFile(seedDir string) (string, error) {
	var torrentFiles []string

	err := filepath.Walk(seedDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.ToLower(filepath.Ext(path)) == ".torrent" {
			torrentFiles = append(torrentFiles, path)
		}
		return nil
	})

	if err != nil {
		return "", err
	}

	if len(torrentFiles) == 0 {
		return "", fmt.Errorf("未找到torrent文件")
	}

	// 如果有多个torrent文件，选择最大的一个（通常是主要的种子文件）
	if len(torrentFiles) > 1 {
		sort.Slice(torrentFiles, func(i, j int) bool {
			infoI, _ := os.Stat(torrentFiles[i])
			infoJ, _ := os.Stat(torrentFiles[j])
			return infoI.Size() > infoJ.Size()
		})
	}

	return torrentFiles[0], nil
}

// 获取种子标题（从Python API调用）
func getSeedTitle(torrentID, siteName string) (string, error) {
	// 调用Python API获取种子信息 - 使用GET方法和URL参数
	url := fmt.Sprintf("%s/api/migrate/get_db_seed_info?torrent_id=%s&site_name=%s",
		coreAPIURL, torrentID, siteName)

	client := &http.Client{Timeout: 10 * time.Second}

	// 创建GET请求
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return "", fmt.Errorf("创建HTTP请求失败: %v", err)
	}

	// 设置请求头
	if internalSecret != "" {
		req.Header.Set("X-Internal-API-Key", generateInternalToken())
	}

	// 发送请求
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("HTTP请求失败: %v", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("读取响应失败: %v", err)
	}

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("HTTP错误 %d: %s", resp.StatusCode, string(body))
	}

	var result map[string]interface{}
	if err := json.Unmarshal(body, &result); err != nil {
		return "", fmt.Errorf("JSON解析失败: %v", err)
	}

	if success, ok := result["success"].(bool); !ok || !success {
		message := "未知错误"
		if msg, ok := result["message"].(string); ok {
			message = msg
		}
		return "", fmt.Errorf("API调用失败: %s", message)
	}

	if data, ok := result["data"].(map[string]interface{}); ok {
		if title, ok := data["title"].(string); ok {
			return title, nil
		}
	}

	return "", fmt.Errorf("响应中未找到种子标题")
}

// 清理文件名（与Python逻辑保持一致）
func sanitizeFilename(title string) string {
	// 移除或替换不安全的字符
	reg := regexp.MustCompile(`[\\/*?:"<>|]`)
	safe := reg.ReplaceAllString(title, "_")

	// 限制长度为150字符
	if len(safe) > 150 {
		safe = safe[:150]
	}

	return safe
}

// 检查视频文件大小（通过解析torrent文件）
func checkVideoSize(torrentID, siteName string) (float64, string, string, error) {
	logInfo("     🔍 检查种子大小: %s@%s", torrentID, siteName)

	// 获取种子标题
	title, err := getSeedTitle(torrentID, siteName)
	if err != nil {
		// ✨ 即使获取标题失败，也返回空标题，让过滤流程继续
		return 0, "", "", fmt.Errorf("获取种子标题失败: %v", err)
	}

	// 构造种子目录路径
	safeName := sanitizeFilename(title)
	seedDir := filepath.Join(tempDir, safeName)

	// 检查目录是否存在，如果不存在则下载种子文件
	if _, err := os.Stat(seedDir); os.IsNotExist(err) {
		err := downloadTorrentFile(torrentID, siteName)
		if err != nil {
			return 0, "", title, fmt.Errorf("下载种子文件失败: %v", err) // ✨ 返回 title
		}
	}

	// 查找torrent文件
	torrentPath, err := findTorrentFile(seedDir)
	if err != nil {
		// 如果找不到torrent文件，尝试下载
		downloadErr := downloadTorrentFile(torrentID, siteName)
		if downloadErr != nil {
			return 0, "", title, fmt.Errorf("下载torrent文件失败: %v", downloadErr) // ✨ 返回 title
		}

		// 下载成功后重新查找
		torrentPath, err = findTorrentFile(seedDir)
		if err != nil {
			return 0, "", title, fmt.Errorf("下载后仍无法找到torrent文件: %v", err) // ✨ 返回 title
		}
	}

	// 解析torrent文件获取大小信息
	sizeGB, largestFile, err := extractVideoSizeFromTorrent(torrentPath)
	if err != nil {
		return 0, "", title, fmt.Errorf("解析torrent文件失败: %v", err) // ✨ 返回 title
	}

	logInfo("     ✅ 解析完成: %.2fGB (%s)", sizeGB, largestFile)

	// ✨ 返回解析出的大小、最大文件名和获取到的标题
	return sizeGB, largestFile, title, nil
}

// 下载种子文件（不进行数据解析或存储）
func downloadTorrentFile(torrentID, siteName string) error {
	// 站点请求频率控制
	waitForSiteRequest(siteName)

	downloadReq := map[string]interface{}{
		"torrent_id": torrentID,
		"site_name":  siteName,
	}

	resp, err := callPythonAPI("/api/migrate/download_torrent_only", downloadReq)
	if err != nil {
		return fmt.Errorf("调用下载API失败: %v", err)
	}

	if success, ok := resp["success"].(bool); !ok || !success {
		message := "未知错误"
		if msg, ok := resp["message"].(string); ok {
			message = msg
		}
		return fmt.Errorf("下载失败: %s", message)
	}

	return nil
}

// 过滤种子
func filterSeeds(seeds []SeedInfo, options *FilterOptions) ([]SeedInfo, []SeedResult, FilterStats) {
	// 强制启用大小过滤进行测试
	logInfo("🔍 强制启用大小过滤进行torrent解析测试")

	var validSeeds []SeedInfo
	var filteredSeeds []SeedResult
	var totalSize float64
	var videoCount int
	var largestVideo, smallestVideo string
	var largestSize, smallestSize float64 = 0, 999999

	// 硬编码5GB限制，防止被修改
	const minSizeGB = 1.0

	logInfo("开始过滤种子，最小大小要求: %.1fGB", minSizeGB)

	for i, seed := range seeds {
		logInfo("[%d/%d] 检查种子: %s", i+1, len(seeds), seed.TorrentID)
		sizeGB, _, title, err := checkVideoSize(seed.TorrentID, seed.SiteName)

		if err != nil {
			logInfo("  ❌ 检查失败: %v", err)
			filteredSeeds = append(filteredSeeds, SeedResult{
				TorrentID:    seed.TorrentID,
				Title:        title,
				Status:       "filtered",
				FilterReason: fmt.Sprintf("检查大小失败: %v", err),
			})
			continue
		}

		// 将视频大小保存到seed中，供后续使用
		seed.VideoSizeGB = sizeGB

		// 更新统计信息
		totalSize += sizeGB
		videoCount++

		if sizeGB > largestSize {
			largestSize = sizeGB
			largestVideo = fmt.Sprintf("%s (%.2fGB)", seed.TorrentID, sizeGB)
		}

		if sizeGB < smallestSize {
			smallestSize = sizeGB
			smallestVideo = fmt.Sprintf("%s (%.2fGB)", seed.TorrentID, sizeGB)
		}

		// 检查大小过滤
		if sizeGB < minSizeGB {
			logInfo("  🚫 过滤: %.2fGB < %.1fGB", sizeGB, minSizeGB)
			filteredSeeds = append(filteredSeeds, SeedResult{
				TorrentID:    seed.TorrentID,
				Status:       "filtered",
				Title:        title,
				VideoSizeGB:  sizeGB,
				FilterReason: fmt.Sprintf("小于 %.1fGB", minSizeGB),
			})
		} else {
			logInfo("  ✅ 通过: %.2fGB", sizeGB)
			validSeeds = append(validSeeds, seed) // 这里的seed已经包含了VideoSizeGB
		}
	}

	stats := FilterStats{
		TotalSeeds:    len(seeds),
		SizeFiltered:  len(filteredSeeds),
		LargestVideo:  largestVideo,
		SmallestVideo: smallestVideo,
	}

	if videoCount > 0 {
		stats.AverageSize = totalSize / float64(videoCount)
	}

	return validSeeds, filteredSeeds, stats
}

// 健康检查
func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":    "healthy",
		"timestamp": time.Now().Format(time.RFC3339),
		"service":   "batch-enhancer",
	})
}

// 批量转种增强处理
func batchEnhanceHandler(w http.ResponseWriter, r *http.Request) {
	// 设置CORS头，允许前端跨域访问
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
	w.Header().Set("Content-Type", "application/json")

	// 处理预检请求
	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}

	// 记录请求开始
	logInfo("🎯 收到批量转种请求")

	// 解析请求
	var req BatchRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorMsg := fmt.Sprintf("JSON解析失败: %v", err)
		logError("❌ 请求错误: %s", errorMsg)
		http.Error(w, `{"success":false,"error":"Invalid JSON"}`, http.StatusBadRequest)
		return
	}

	// 验证请求
	if req.TargetSiteName == "" {
		logError("❌ 请求错误: 缺少目标站点名称")
		http.Error(w, `{"success":false,"error":"target_site_name is required"}`, http.StatusBadRequest)
		return
	}

	if len(req.Seeds) == 0 {
		logError("❌ 请求错误: 种子列表为空")
		http.Error(w, `{"success":false,"error":"seeds cannot be empty"}`, http.StatusBadRequest)
		return
	}

	logSuccess("✅ 请求验证通过: %s, %d个种子", req.TargetSiteName, len(req.Seeds))

	// 处理批量转种
	logInfo("🚀 开始批量转种处理...")
	startTime := time.Now()
	result := processBatchSeeds(req)
	duration := time.Since(startTime)

	logInfo("⏱️  批量转种处理完成，耗时: %v", duration)
	logInfo("📊 处理结果: %s", result.Message)

	// 返回结果
	json.NewEncoder(w).Encode(result)
}

// 种子处理记录查看处理
func recordsHandler(w http.ResponseWriter, r *http.Request) {
	// 设置CORS头，允许前端跨域访问
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, DELETE, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
	w.Header().Set("Content-Type", "application/json")

	// 处理预检请求
	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}

	switch r.Method {
	case "GET":
		// 从Python后端获取种子处理记录 - 使用HTTP GET方法
		client := &http.Client{Timeout: 10 * time.Second}
		url := coreAPIURL + "/api/batch-enhance/records?page=1&page_size=1000"

		req, err := http.NewRequest("GET", url, nil)
		if err != nil {
			// 如果创建请求失败，返回错误
			response := RecordResponse{
				Success: false,
				Error:   fmt.Sprintf("创建HTTP请求失败: %v", err),
			}
			json.NewEncoder(w).Encode(response)
			return
		}

		// 设置认证头
		if internalSecret != "" {
			req.Header.Set("X-Internal-API-Key", generateInternalToken())
		}

		resp, err := client.Do(req)
		if err != nil {
			// 如果Python API不可用，返回错误
			response := RecordResponse{
				Success: false,
				Error:   fmt.Sprintf("Python API不可用: %v", err),
			}
			json.NewEncoder(w).Encode(response)
			return
		}
		defer resp.Body.Close()

		body, err := io.ReadAll(resp.Body)
		if err != nil || resp.StatusCode != http.StatusOK {
			// 如果API调用失败，返回错误
			response := RecordResponse{
				Success: false,
				Error:   fmt.Sprintf("API调用失败: HTTP %d", resp.StatusCode),
			}
			json.NewEncoder(w).Encode(response)
			return
		}

		// 直接转发Python API的响应
		w.Header().Set("Content-Type", "application/json")
		w.Write(body)

	case "DELETE":
		// 调用Python API清空记录 - 使用HTTP DELETE方法
		client := &http.Client{Timeout: 10 * time.Second}
		url := coreAPIURL + "/api/batch-enhance/records"

		req, err := http.NewRequest("DELETE", url, nil)
		if err != nil {
			response := RecordResponse{
				Success: false,
				Error:   fmt.Sprintf("创建HTTP请求失败: %v", err),
			}
			json.NewEncoder(w).Encode(response)
			return
		}

		// 设置认证头
		if internalSecret != "" {
			req.Header.Set("X-Internal-API-Key", generateInternalToken())
		}
		req.Header.Set("Content-Type", "application/json")

		resp, err := client.Do(req)
		if err != nil {
			response := RecordResponse{
				Success: false,
				Error:   fmt.Sprintf("Python API不可用: %v", err),
			}
			json.NewEncoder(w).Encode(response)
			return
		}
		defer resp.Body.Close()

		// 直接转发Python API的响应
		body, _ := io.ReadAll(resp.Body)
		w.Header().Set("Content-Type", "application/json")
		w.Write(body)

	default:
		http.Error(w, `{"success":false,"error":"Method not allowed"}`, http.StatusMethodNotAllowed)
	}
}

// 从map中安全获取字符串值的辅助函数
func getStringFromMap(m map[string]interface{}, key string) string {
	if val, ok := m[key]; ok && val != nil {
		if str, ok := val.(string); ok {
			return str
		}
	}
	return ""
}

// 从种子列表中获取指定TorrentID的源站点
func getSourceSiteFromSeeds(seeds []SeedInfo, torrentID string) string {
	for _, seed := range seeds {
		if seed.TorrentID == torrentID {
			logInfo("找到源站点: %s for %s", seed.SiteName, torrentID)
			return seed.Nickname
		}
	}
	return ""
}

// 核心批量处理逻辑
func processBatchSeeds(req BatchRequest) BatchResponse {
	// 生成新的批次ID
	currentBatchID = generateBatchID()
	logInfo("📋 开始批量处理种子，批次ID: %s", currentBatchID)

	var processedSeeds []SeedResult
	var failedSeeds []SeedResult

	// 首先应用过滤逻辑
	logInfo("🔍 应用过滤逻辑...")
	filterStart := time.Now()
	validSeeds, filteredSeeds, filterStats := filterSeeds(req.Seeds, req.FilterOptions)
	filterDuration := time.Since(filterStart)

	logInfo("⏱️  过滤完成，耗时: %v", filterDuration)
	logInfo("📊 过滤结果: 总共 %d 个种子, 通过过滤 %d 个, 被过滤 %d 个",
		len(req.Seeds), len(validSeeds), len(filteredSeeds))

	// 如果没有有效种子，直接返回
	if len(validSeeds) == 0 {
		logWarning("⚠️  所有种子都被过滤，没有种子需要处理")
		return BatchResponse{
			Success: true,
			Message: fmt.Sprintf("所有 %d 个种子都被过滤，没有种子需要处理", len(req.Seeds)),
			Data: &BatchData{
				TargetSiteName: req.TargetSiteName,
				SeedsProcessed: 0,
				SeedsFailed:    0,
				SeedsFiltered:  len(filteredSeeds),
				ProcessedSeeds: []SeedResult{},
				FailedSeeds:    []SeedResult{},
				FilteredSeeds:  filteredSeeds,
				FilterStats:    filterStats,
			},
		}
	}

	// 首先记录所有被过滤的种子到数据库
	for _, filteredSeed := range filteredSeeds {
		record := SeedRecord{
			BatchID:     currentBatchID,
			TorrentID:   filteredSeed.TorrentID,
			Title:       filteredSeed.Title,
			SourceSite:  getSourceSiteFromSeeds(req.Seeds, filteredSeed.TorrentID),
			TargetSite:  req.TargetSiteName,
			VideoSizeGB: filteredSeed.VideoSizeGB,
			Status:      "filtered",
			ErrorDetail: filteredSeed.FilterReason,
		}
		if err := recordSeedResult(record); err != nil {
			logError("记录过滤种子到数据库失败: %v", err)
		}
	}

	// 串行处理有效种子(站点请求频率由全局控制)
	logInfo("🔄 开始串行处理 %d 个有效种子...", len(validSeeds))
	processStart := time.Now()

	for i, seed := range validSeeds {
		logInfo("🔄 [%d/%d] 开始处理种子: %s -> %s",
			i+1, len(validSeeds), seed.TorrentID, req.TargetSiteName)

		seedStart := time.Now()

		// === 主要修改点 ===
		// 调用 processSingleSeed 时传入进度信息
		result := processSingleSeed(seed, req.TargetSiteName, i+1, len(validSeeds))
		// =================

		seedDuration := time.Since(seedStart)

		if result.Status == "success" {
			logSuccess("✅ [%d/%d] 种子处理成功: %s (耗时: %v)",
				i+1, len(validSeeds), seed.TorrentID, seedDuration)
			processedSeeds = append(processedSeeds, result)
		} else {
			logError("❌ [%d/%d] 种子处理失败: %s - %s (耗时: %v)",
				i+1, len(validSeeds), seed.TorrentID, result.Error, seedDuration)
			failedSeeds = append(failedSeeds, result)
		}
	}

	processDuration := time.Since(processStart)
	logInfo("⏱️  所有种子处理完成，耗时: %v", processDuration)
	logInfo("📊 最终统计:")
	logInfo("   - 成功处理: %d 个", len(processedSeeds))
	logInfo("   - 处理失败: %d 个", len(failedSeeds))
	logInfo("   - 过滤排除: %d 个", len(filteredSeeds))

	return BatchResponse{
		Success: true,
		Message: fmt.Sprintf("处理完成: 总共 %d 个种子, 过滤掉 %d 个, 成功处理 %d 个, 失败 %d 个",
			len(req.Seeds), len(filteredSeeds), len(processedSeeds), len(failedSeeds)),
		Data: &BatchData{
			TargetSiteName: req.TargetSiteName,
			SeedsProcessed: len(processedSeeds),
			SeedsFailed:    len(failedSeeds),
			SeedsFiltered:  len(filteredSeeds),
			ProcessedSeeds: processedSeeds,
			FailedSeeds:    failedSeeds,
			FilteredSeeds:  filteredSeeds,
			FilterStats:    filterStats,
		},
	}
}

// 处理单个种子
func processSingleSeed(seed SeedInfo, targetSite string, currentIndex int, totalSeeds int) SeedResult {
	// 获取种子信息和task_id
	taskID, seedData, err := getSeedTaskIDAndData(seed.TorrentID, seed.SiteName)
	if err != nil {
		return SeedResult{
			TorrentID: seed.TorrentID,
			Status:    "failed",
			Error:     fmt.Sprintf("获取种子信息失败: %v", err),
		}
	}

	// 计算种子目录路径
	title := getStringValue(seedData, "title")
	if title == "" {
		return SeedResult{
			TorrentID: seed.TorrentID,
			Status:    "failed",
			Error:     "种子标题为空",
		}
	}

	// 使用与checkVideoSize相同的逻辑构造种子目录路径
	safeName := sanitizeFilename(title)
	seedDir := filepath.Join(tempDir, safeName)

	// 构造完整的upload_data
	uploadData := constructUploadData(seedData, seedDir)

	// 调用现有的转种发布API
	// 站点请求频率控制
	waitForSiteRequest(targetSite)

	// === 主要修改点：添加进度信息 ===
	// 构造进度字符串，例如 "[1/10]"
	progressInfo := fmt.Sprintf("%d/%d", currentIndex, totalSeeds)
	// === 主要修改点结束 ===

	publishReq := map[string]interface{}{
		"task_id":                taskID,
		"targetSite":             targetSite,
		"sourceSite":             seed.SiteName,
		"nickname":               seed.Nickname,
		"auto_add_to_downloader": true,             // 启用自动添加
		"batch_id":               currentBatchID,   // 传递批次ID给Python端
		"video_size_gb":          seed.VideoSizeGB, // 传递视频大小
		"batch_progress":         progressInfo,     // 添加进度信息
	}

	// 将 uploadData 添加到请求中
	publishReq["upload_data"] = uploadData

	resp, err := callPythonAPI("/api/migrate/publish", publishReq)
	if err != nil {
		return SeedResult{
			TorrentID: seed.TorrentID,
			Status:    "failed",
			Error:     err.Error(),
		}
	}

	// 解析响应
	if resp["success"] == true {
		result := SeedResult{
			TorrentID: seed.TorrentID,
			Status:    "success",
			URL:       getStringValue(resp, "url"),
		}
		return result
	}

	// 处理失败情况
	errorMsg := "Unknown error"
	if logs, ok := resp["logs"].(string); ok {
		errorMsg = logs
	} else if errStr, ok := resp["error"].(string); ok {
		errorMsg = errStr
	}

	return SeedResult{
		TorrentID: seed.TorrentID,
		Status:    "failed",
		Error:     errorMsg,
	}
}

// 获取种子信息、task_id和完整的种子数据
func getSeedTaskIDAndData(torrentID, siteName string) (string, map[string]interface{}, error) {
	// 使用GET方法调用get_db_seed_info获取task_id和数据
	url := fmt.Sprintf("%s/api/migrate/get_db_seed_info?torrent_id=%s&site_name=%s",
		coreAPIURL, torrentID, siteName)

	client := &http.Client{Timeout: 10 * time.Second}

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return "", nil, fmt.Errorf("创建HTTP请求失败: %v", err)
	}

	// 设置认证头
	if internalSecret != "" {
		req.Header.Set("X-Internal-API-Key", generateInternalToken())
	}

	resp, err := client.Do(req)
	if err != nil {
		return "", nil, fmt.Errorf("HTTP请求失败: %v", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", nil, fmt.Errorf("读取响应失败: %v", err)
	}

	if resp.StatusCode != http.StatusOK {
		return "", nil, fmt.Errorf("HTTP错误 %d: %s", resp.StatusCode, string(body))
	}

	var result map[string]interface{}
	if err := json.Unmarshal(body, &result); err != nil {
		return "", nil, fmt.Errorf("JSON解析失败: %v", err)
	}

	if success, ok := result["success"].(bool); !ok || !success {
		message := "未知错误"
		if msg, ok := result["message"].(string); ok {
			message = msg
		}
		return "", nil, fmt.Errorf("API调用失败: %s", message)
	}

	taskID, ok1 := result["task_id"].(string)
	data, ok2 := result["data"].(map[string]interface{})

	if !ok1 {
		return "", nil, fmt.Errorf("响应中未找到task_id")
	}
	if !ok2 {
		return "", nil, fmt.Errorf("响应中未找到data")
	}

	return taskID, data, nil
}

// 从数据库种子数据构造upload_data
func constructUploadData(seedData map[string]interface{}, seedDir string) map[string]interface{} {
	uploadData := map[string]interface{}{
		"title":       getStringValue(seedData, "title"),
		"subtitle":    getStringValue(seedData, "subtitle"),
		"imdb_link":   getStringValue(seedData, "imdb_link"),
		"douban_link": getStringValue(seedData, "douban_link"),
		"mediainfo":   getStringValue(seedData, "mediainfo"),
		"torrent_dir": seedDir, // 添加种子目录路径，确保上传参数文件保存在正确的目录
	}

	// 处理intro对象
	var statement, poster, body, screenshots string
	if intro, ok := seedData["intro"].(map[string]interface{}); ok {
		statement = getStringValue(intro, "statement")
		poster = getStringValue(intro, "poster")
		body = getStringValue(intro, "body")
		screenshots = getStringValue(intro, "screenshots")

		uploadData["intro"] = map[string]interface{}{
			"statement":   statement,
			"poster":      poster,
			"body":        body,
			"screenshots": screenshots,
		}
	} else {
		// 如果intro不存在，从数据库顶级字段读取
		statement = getStringValue(seedData, "statement")
		poster = getStringValue(seedData, "poster")
		body = getStringValue(seedData, "body")
		screenshots = getStringValue(seedData, "screenshots")

		uploadData["intro"] = map[string]interface{}{
			"statement":   statement,
			"poster":      poster,
			"body":        body,
			"screenshots": screenshots,
		}
	}

	// 构造完整的description（遵循crabpt.py的格式）
	description := fmt.Sprintf("%s\n%s\n%s\n%s", statement, poster, body, screenshots)
	uploadData["description"] = description

	// 处理source_params对象
	if sourceParams, ok := seedData["source_params"].(map[string]interface{}); ok {
		uploadData["source_params"] = sourceParams
	} else {
		uploadData["source_params"] = map[string]interface{}{}
	}

	// 处理title_components数组
	if titleComponents, ok := seedData["title_components"].([]interface{}); ok {
		uploadData["title_components"] = titleComponents
	} else {
		uploadData["title_components"] = []interface{}{}
	}

	// 处理standardized_params对象：使用数据库字段 + title_components解析
	standardizedParams := map[string]interface{}{
		// 从数据库读取的标准参数
		"type":        getStringValue(seedData, "type"),
		"medium":      getStringValue(seedData, "medium"),
		"video_codec": getStringValue(seedData, "video_codec"),
		"audio_codec": getStringValue(seedData, "audio_codec"),
		"resolution":  getStringValue(seedData, "resolution"),
		"team":        getStringValue(seedData, "team"),
		"source":      getStringValue(seedData, "source"),
		"tags":        getArrayValue(seedData, "tags"),
	}

	// 从title_components中提取额外的标准参数
	if titleComponents, ok := seedData["title_components"].([]interface{}); ok {
		titleComponentsMap := make(map[string]string)
		for _, component := range titleComponents {
			if comp, ok := component.(map[string]interface{}); ok {
				key := getStringValue(comp, "key")
				value := getStringValue(comp, "value")
				if key != "" && value != "" {
					titleComponentsMap[key] = value
				}
			}
		}

		// 映射title_components到standardized_params的额外字段
		// 注意：不要设置title，因为主标题是独立字段，不在standardized_params中
		if seasonEpisode := titleComponentsMap["季集"]; seasonEpisode != "" {
			standardizedParams["season_episode"] = seasonEpisode
		}
		if year := titleComponentsMap["年份"]; year != "" {
			standardizedParams["year"] = year
		}
		if bitDepth := titleComponentsMap["色深"]; bitDepth != "" {
			standardizedParams["bit_depth"] = bitDepth
		}
		if frameRate := titleComponentsMap["帧率"]; frameRate != "" {
			standardizedParams["frame_rate"] = frameRate
		}
		if hdrFormat := titleComponentsMap["HDR格式"]; hdrFormat != "" {
			standardizedParams["hdr_format"] = hdrFormat
		}
		if videoFormat := titleComponentsMap["视频格式"]; videoFormat != "" {
			standardizedParams["video_format"] = videoFormat
		}
		if platform := titleComponentsMap["片源平台"]; platform != "" {
			standardizedParams["platform"] = platform
		}
		if status := titleComponentsMap["剧集状态"]; status != "" {
			standardizedParams["status"] = status
		}
		if version := titleComponentsMap["发布版本"]; version != "" {
			standardizedParams["version"] = version
		}
	}

	uploadData["standardized_params"] = standardizedParams

	return uploadData
}

// 调用Python API，带重试机制
func callPythonAPI(endpoint string, data map[string]interface{}) (map[string]interface{}, error) {
	return callPythonAPIWithRetry(endpoint, data, 3) // 最多重试3次
}

// 带重试机制的Python API调用
func callPythonAPIWithRetry(endpoint string, data map[string]interface{}, maxRetries int) (map[string]interface{}, error) {
	url := coreAPIURL + endpoint

	jsonData, err := json.Marshal(data)
	if err != nil {
		return nil, fmt.Errorf("JSON序列化失败: %v", err)
	}

	client := &http.Client{Timeout: 30 * time.Second}

	for attempt := 1; attempt <= maxRetries; attempt++ {
		// 创建请求
		req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
		if err != nil {
			return nil, fmt.Errorf("创建HTTP请求失败: %v", err)
		}

		// 设置请求头
		req.Header.Set("Content-Type", "application/json")

		// 使用动态生成的内部认证token
		internalToken := generateInternalToken()
		req.Header.Set("X-Internal-API-Key", internalToken)

		// 发送请求
		resp, err := client.Do(req)
		if err != nil {
			if attempt == maxRetries {
				return nil, fmt.Errorf("HTTP请求失败: %v", err)
			}
			logInfo("     ⚠️  [%d/%d] HTTP请求失败，重试中: %v", attempt, maxRetries, err)
			time.Sleep(5 * time.Second)
			continue
		}
		defer resp.Body.Close()

		body, err := io.ReadAll(resp.Body)
		if err != nil {
			if attempt == maxRetries {
				return nil, fmt.Errorf("读取响应失败: %v", err)
			}
			logInfo("     ⚠️  [%d/%d] 读取响应失败，重试中: %v", attempt, maxRetries, err)
			time.Sleep(5 * time.Second)
			continue
		}

		// 如果是401认证失败，可能是时钟不同步，等待后重试
		if resp.StatusCode == 401 {
			if attempt == maxRetries {
				return nil, fmt.Errorf("认证失败，已重试%d次: %s", maxRetries, string(body))
			}
			logInfo("     🔐 [%d/%d] 认证失败，等待60秒后重试", attempt, maxRetries)
			time.Sleep(60 * time.Second)
			continue
		}

		if resp.StatusCode != http.StatusOK {
			if attempt == maxRetries {
				return nil, fmt.Errorf("HTTP错误 %d: %s", resp.StatusCode, string(body))
			}
			logInfo("     ⚠️  [%d/%d] HTTP错误 %d，重试中", attempt, maxRetries, resp.StatusCode)
			time.Sleep(5 * time.Second)
			continue
		}

		// 成功响应，解析JSON
		var result map[string]interface{}
		if err := json.Unmarshal(body, &result); err != nil {
			if attempt == maxRetries {
				return nil, fmt.Errorf("JSON解析失败: %v", err)
			}
			logInfo("     ⚠️  [%d/%d] JSON解析失败，重试中: %v", attempt, maxRetries, err)
			time.Sleep(5 * time.Second)
			continue
		}

		return result, nil
	}

	return nil, fmt.Errorf("已重试%d次，所有尝试都失败", maxRetries)
}

// 辅助函数
func getStringValue(data map[string]interface{}, key string) string {
	if val, ok := data[key].(string); ok {
		return val
	}
	return ""
}

// 辅助函数：获取数组值
func getArrayValue(data map[string]interface{}, key string) []interface{} {
	if val, ok := data[key].([]interface{}); ok {
		return val
	}
	// 尝试处理可能是JSON字符串的数组
	if str, ok := data[key].(string); ok && str != "" {
		var arr []interface{}
		if err := json.Unmarshal([]byte(str), &arr); err == nil {
			return arr
		}
	}
	return []interface{}{}
}

// 获取原始种子的下载器信息（通过 hash 或 torrent_id 查询）
func getOriginalSeedDownloaderInfo(hash, torrentID, siteName string) (string, string) {
	// 调用Python API获取种子的下载器信息
	url := fmt.Sprintf("%s/api/torrents/info?hash=%s", coreAPIURL, hash)

	client := &http.Client{Timeout: 10 * time.Second}

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		logWarning("创建获取种子信息请求失败: %v", err)
		return "", ""
	}

	// 设置认证头
	if internalSecret != "" {
		req.Header.Set("X-Internal-API-Key", generateInternalToken())
	}

	resp, err := client.Do(req)
	if err != nil {
		logWarning("获取种子信息请求失败: %v", err)
		return "", ""
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		logWarning("获取种子信息返回错误状态码: %d", resp.StatusCode)
		return "", ""
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		logWarning("读取种子信息响应失败: %v", err)
		return "", ""
	}

	var result map[string]interface{}
	if err := json.Unmarshal(body, &result); err != nil {
		logWarning("解析种子信息JSON失败: %v", err)
		return "", ""
	}

	if success, ok := result["success"].(bool); !ok || !success {
		// 如果通过 hash 查询失败，尝试直接从 torrents 表查询
		logInfo("通过 hash 查询失败，尝试通过 torrent_id 查询")
		return getDownloaderInfoFromDB(torrentID, siteName)
	}

	// 从返回的数据中提取 downloader 和 save_path
	if data, ok := result["data"].(map[string]interface{}); ok {
		downloaderId := getStringValue(data, "downloader")
		savePath := getStringValue(data, "save_path")
		return downloaderId, savePath
	}

	return "", ""
}

// 通过 torrent_id 和 site_name 从数据库查询下载器信息
func getDownloaderInfoFromDB(torrentID, siteName string) (string, string) {
	// 构造查询请求
	data := map[string]interface{}{
		"torrent_id": torrentID,
		"site_name":  siteName,
	}

	resp, err := callPythonAPI("/api/migrate/get_downloader_info", data)
	if err != nil {
		logWarning("查询下载器信息失败: %v", err)
		return "", ""
	}

	if success, ok := resp["success"].(bool); !ok || !success {
		return "", ""
	}

	downloaderId := getStringValue(resp, "downloader_id")
	savePath := getStringValue(resp, "save_path")

	return downloaderId, savePath
}

// 测试核心API连接
func testCoreAPIConnection() error {
	url := coreAPIURL + "/health"
	client := &http.Client{Timeout: 5 * time.Second}

	resp, err := client.Get(url)
	if err != nil {
		return fmt.Errorf("连接失败: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("状态码异常: %d", resp.StatusCode)
	}

	return nil
}

func main() {
	// 设置日志格式，包含时间戳和文件位置
	log.SetFlags(log.LstdFlags | log.Lshortfile)

	log.Println("==========================================")
	log.Println("🚀 PT Nexus 批量转种增强服务启动中...")
	log.Println("==========================================")

	// 初始化日志系统
	logInfo("📝 初始化日志系统...")
	if err := initLogging(); err != nil {
		log.Fatalf("❌ 初始化日志系统失败: %v", err)
	}
	logSuccess("✅ 日志系统初始化完成")

	// 显示配置信息
	logInfo("📊 服务配置:")
	logInfo("   - 服务端口: %s", port)
	logInfo("   - 核心API地址: %s", coreAPIURL)
	logInfo("   - 临时目录: %s", tempDir)
	logInfo("   - 视频大小过滤阈值: 1.0GB (硬编码)")
	logInfo("   - 站点请求间隔: %v (全局控制)", minRequestInterval)
	logInfo("   - 内部认证方式: 网络隔离 + API Key")
	if internalSecret != "" && internalSecret != "pt-nexus-2024-secret-key" {
		logInfo("   - 内部认证密钥: 已自定义")
	} else {
		logWarning("   - 内部认证密钥: 使用默认值")
	}

	// 检查临时目录
	if _, err := os.Stat(tempDir); os.IsNotExist(err) {
		logWarning("⚠️  警告: 临时目录不存在，尝试创建: %s", tempDir)
		if err := os.MkdirAll(tempDir, 0755); err != nil {
			log.Fatalf("❌ 致命错误: 无法创建临时目录 %s: %v", tempDir, err)
		}
		logSuccess("✅ 临时目录创建成功: %s", tempDir)
	} else {
		logSuccess("✅ 临时目录检查通过: %s", tempDir)
	}

	// 检测核心API连接
	logInfo("🔗 检测核心API连接...")
	if err := testCoreAPIConnection(); err != nil {
		logWarning("⚠️  警告: 核心API连接失败: %v", err)
		logInfo("   服务将继续启动，但功能可能受限")
	} else {
		logSuccess("✅ 核心API连接正常")
	}

	// 路由设置
	logInfo("🛠️  设置API路由...")
	http.HandleFunc("/health", healthHandler)
	http.HandleFunc("/batch-enhance", batchEnhanceHandler)
	http.HandleFunc("/records", recordsHandler)
	logInfo("   - GET  /health         健康检查")
	logInfo("   - POST /batch-enhance  批量转种增强")
	logInfo("   - GET  /records        查看处理记录")
	logInfo("   - DELETE /records      清空处理记录")

	// 启动服务器
	logSuccess("🌟 批量转种增强服务已启动!")
	logInfo("   访问地址: http://localhost:%s", port)
	logInfo("   健康检查: http://localhost:%s/health", port)
	log.Println("==========================================")

	if err := http.ListenAndServe(":"+port, nil); err != nil {
		logError("❌ 服务器启动失败: %v", err)
		log.Fatalf("❌ 服务器启动失败: %v", err)
	}
}
