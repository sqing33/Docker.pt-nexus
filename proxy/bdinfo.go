// bdinfo.go
package main

import (
	"bufio"
	"bytes" // 【新增】需要引入 bytes 包
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

// BDInfoRequest BDInfo提取请求结构体
type BDInfoRequest struct {
	RemotePath  string `json:"remote_path"`
	TaskID      string `json:"task_id"`
	CallbackURL string `json:"callback_url,omitempty"`
}

// BDInfoResponse BDInfo提取响应结构体
type BDInfoResponse struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
	BDInfo  string `json:"bdinfo,omitempty"`
	TaskID  string `json:"task_id,omitempty"`
}

// BDInfoProgress BDInfo处理进度结构体
type BDInfoProgress struct {
	TaskID          string  `json:"task_id"`
	ProgressPercent float64 `json:"progress_percent"`
	CurrentFile     string  `json:"current_file"`
	ElapsedTime     string  `json:"elapsed_time"`
	RemainingTime   string  `json:"remaining_time"`
	Status          string  `json:"status"`
	DiscSize        int64   `json:"disc_size,omitempty"`
}

// BDInfoTaskStatus BDInfo任务状态存储
type BDInfoTaskStatus struct {
	TaskID          string    `json:"task_id"`
	ProgressPercent float64   `json:"progress_percent"`
	CurrentFile     string    `json:"current_file"`
	ElapsedTime     string    `json:"elapsed_time"`
	RemainingTime   string    `json:"remaining_time"`
	Status          string    `json:"status"` // "running", "completed", "failed"
	StartTime       time.Time `json:"start_time"`
	EndTime         time.Time `json:"end_time,omitempty"`
	BDInfoContent   string    `json:"bdinfo_content,omitempty"`
	ErrorMessage    string    `json:"error_message,omitempty"`
	DiscSize        int64     `json:"disc_size,omitempty"`
}

// 全局进度存储，使用互斥锁保护
var (
	progressStore = make(map[string]*BDInfoTaskStatus)
	progressMutex sync.RWMutex
)

// isBlurayDisc 检查给定路径是否是蓝光原盘目录
func isBlurayDisc(path string) bool {
	// 1. 尝试查找 BDMV 目录 (通常是大写，但为了保险也检查小写)
	bdmvPath := filepath.Join(path, "BDMV")
	info, err := os.Stat(bdmvPath)
	if err != nil || !info.IsDir() {
		// 尝试小写 bdmv
		bdmvPath = filepath.Join(path, "bdmv")
		info, err = os.Stat(bdmvPath)
		if err != nil || !info.IsDir() {
			return false
		}
	}

	// 2. 检查 BDMV 目录下是否存在索引文件
	candidates := []string{
		"index.bdmv", "INDEX.BDMV",
		"index.bdm", "INDEX.BDM",
		"MovieObject.bdmv", "MOVIEOBJECT.BDMV",
	}

	for _, name := range candidates {
		targetFile := filepath.Join(bdmvPath, name)
		if _, err := os.Stat(targetFile); err == nil {
			return true
		}
	}

	return false
}

// extractBDInfoWithProgress 提取蓝光原盘的BDInfo信息（带进度监控）
func extractBDInfoWithProgress(blurayPath string, taskID string, callbackURL string) (string, error) {
	if !isBlurayDisc(blurayPath) {
		return "", fmt.Errorf("路径不是有效的蓝光原盘目录: %s", blurayPath)
	}

	tempFile, err := os.CreateTemp("", "bdinfo-*.txt")
	if err != nil {
		return "", fmt.Errorf("创建临时文件失败: %v", err)
	}
	tempFile.Close()
	defer os.Remove(tempFile.Name())

	bdinfoPath := "./bdinfo/BDInfo"
	args := []string{"-p", blurayPath, "-o", tempFile.Name(), "-m"}

	fmt.Printf("开始执行 BDInfo 命令（带进度监控）: %s %v\n", bdinfoPath, args)

	err = executeBDInfoWithProgressMonitoring(bdinfoPath, args, taskID, callbackURL)
	if err != nil {
		return "", fmt.Errorf("BDInfo执行失败: %v", err)
	}

	content, err := os.ReadFile(tempFile.Name())
	if err != nil {
		return "", fmt.Errorf("读取BDInfo输出文件失败: %v", err)
	}

	bdinfoContent := string(content)
	if bdinfoContent == "" {
		return "", fmt.Errorf("BDInfo生成的内容为空")
	}

	fmt.Printf("BDInfo 原始提取完成，内容长度: %d 字节\n", len(bdinfoContent))

	processedContent, err := ProcessBDInfo(tempFile.Name())
	if err != nil {
		fmt.Printf("BDInfoDataSubstractor 处理失败，使用原始内容: %v\n", err)
		processedContent = filterEmptyLines(bdinfoContent)
	} else {
		fmt.Printf("BDInfoDataSubstractor 处理成功，处理后内容长度: %d 字节\n", len(processedContent))
	}

	fmt.Printf("BDInfo 完整处理完成，最终内容长度: %d 字节\n", len(processedContent))
	return processedContent, nil
}

// extractBDInfo 提取蓝光原盘的BDInfo信息（原版，保持兼容性）
func extractBDInfo(blurayPath string, taskID string) (string, error) {
	return extractBDInfoWithProgress(blurayPath, taskID, "")
}

// 【新增】自定义分割函数，同时支持 \r 和 \n 作为分隔符
func scanCROrLF(data []byte, atEOF bool) (advance int, token []byte, err error) {
	if atEOF && len(data) == 0 {
		return 0, nil, nil
	}
	// 查找 \r 或 \n
	if i := bytes.IndexAny(data, "\r\n"); i >= 0 {
		// 返回数据直到分隔符（但不包含分隔符），并跳过分隔符（+1）
		return i + 1, data[0:i], nil
	}
	// 如果到了EOF，返回剩余所有数据
	if atEOF {
		return len(data), data, nil
	}
	// 请求更多数据
	return 0, nil, nil
}

// executeBDInfoWithProgressMonitoring 执行BDInfo命令并监控进度
func executeBDInfoWithProgressMonitoring(bdinfoPath string, args []string, taskID string, callbackURL string) error {
	cmd := exec.Command(bdinfoPath, args...)

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("创建stdout管道失败: %v", err)
	}

	stderr, err := cmd.StderrPipe()
	if err != nil {
		return fmt.Errorf("创建stderr管道失败: %v", err)
	}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("启动BDInfo命令失败: %v", err)
	}

	go func() {
		defer stdout.Close()
		defer stderr.Close()

		reader := io.MultiReader(stdout, stderr)
		scanner := bufio.NewScanner(reader)

		// 使用自定义的分割函数，支持识别 \r
		scanner.Split(scanCROrLF)

		progressPattern := regexp.MustCompile(`Scanning (.+?)\s+\|\s+Progress:\s+([\d.]+)%\s+\|\s+Elapsed:\s+([\d:]+)\s+\|\s+Remaining:\s+([\d:]+)`)
		discSizePattern := regexp.MustCompile(`Disc Size:\s+([\d,]+)\s+bytes`)

		// 用于记录上一行是否是进度条，以便正确换行
		lastLineWasProgress := false
		var discSize int64 = 0

		for scanner.Scan() {
			line := scanner.Text()

			// 过滤掉空行
			if strings.TrimSpace(line) == "" {
				continue
			}

			// 解析Disc Size (保持原样，这个只出现一次)
			discMatch := discSizePattern.FindStringSubmatch(line)
			if discMatch != nil {
				if lastLineWasProgress {
					fmt.Println() // 补一个换行
					lastLineWasProgress = false
				}
				discSizeStr := strings.ReplaceAll(discMatch[1], ",", "")
				fmt.Printf("[DEBUG] Disc Size: %s bytes\n", discSizeStr)
				
				// 解析并存储Disc Size
				if parsedSize, err := strconv.ParseInt(discSizeStr, 10, 64); err == nil {
					discSize = parsedSize
					// 更新任务状态中的Disc Size
					updateDiscSize(taskID, discSize)
				}
			}

			// 解析进度信息
			match := progressPattern.FindStringSubmatch(line)
			if match != nil {
				// === 核心修改开始 ===

				// 1. 在控制台/日志中只使用 \r 回到行首，不换行
				// 注意：在 tail -f 中，\r 会覆盖当前行
				fmt.Printf("\r%s", line)
				lastLineWasProgress = true

				// 解析数据用于回调 (但不打印 [DEBUG] 日志到控制台了)
				currentFile := match[1]
				progressStr := match[2]
				elapsedTime := match[3]
				remainingTime := match[4]

				progressPercent := 0.0
				if p, err := strconv.ParseFloat(progressStr, 64); err == nil {
					progressPercent = p
				}

				// 注释掉这行 DEBUG 打印，因为它会强制换行，破坏单行显示效果
				// fmt.Printf("[DEBUG] 进度更新: %.2f%%, 文件: %s, 已用时: %s, 剩余: %s\n",
				// 	progressPercent, currentFile, elapsedTime, remainingTime)

				// 更新内存存储中的进度
				updateProgress(taskID, progressPercent, currentFile, elapsedTime, remainingTime, "running")
				
				// 发送回调保持不变
				if callbackURL != "" {
					sendProgressCallback(callbackURL, taskID, progressPercent, currentFile, elapsedTime, remainingTime)
				}
				// === 核心修改结束 ===

			} else {
				// 如果不是进度条（例如 Scan complete），且上一行是进度条，先打印个换行
				if lastLineWasProgress {
					fmt.Println()
					lastLineWasProgress = false
				}
				// 普通日志正常换行打印
				fmt.Println(line)
			}
		}
		// 循环结束，补一个换行确保整洁
		if lastLineWasProgress {
			fmt.Println()
		}
	}()

	done := make(chan error, 1)
	go func() {
		done <- cmd.Wait()
	}()

	select {
	case <-time.After(60 * time.Minute):
		cmd.Process.Kill()
		return fmt.Errorf("BDInfo执行超时")
	case err := <-done:
		if err != nil {
			return fmt.Errorf("BDInfo命令执行失败: %v", err)
		}
		return nil
	}
}

// sendProgressCallback 发送进度回调
func sendProgressCallback(callbackURL, taskID string, progressPercent float64, currentFile, elapsedTime, remainingTime string) {
	if callbackURL == "" {
		return
	}

	// 获取当前任务状态以包含Disc Size
	task, exists := getTask(taskID)
	var discSize int64 = 0
	if exists {
		discSize = task.DiscSize
	}

	progressData := BDInfoProgress{
		TaskID:          taskID,
		ProgressPercent: progressPercent,
		CurrentFile:     currentFile,
		ElapsedTime:     elapsedTime,
		RemainingTime:   remainingTime,
		Status:          "running",
		DiscSize:        discSize,
	}

	jsonData, err := json.Marshal(progressData)
	if err != nil {
		fmt.Printf("编码进度数据失败: %v\n", err)
		return
	}

	progressURL := callbackURL + "/progress"
	
	// 创建带超时的HTTP客户端
	client := &http.Client{
		Timeout: 180 * time.Second, // 180秒超时
	}
	
	resp, err := client.Post(progressURL, "application/json", strings.NewReader(string(jsonData)))
	if err != nil {
		// 回调失败通常不需要中断主流程，打印错误即可
		fmt.Printf("发送进度回调失败: %v\n", err)
		return
	}
	defer resp.Body.Close()
}

// sendCompletionCallback 发送完成回调
func sendCompletionCallback(callbackURL, taskID string, success bool, bdinfoContent, errorMessage string) {
	if callbackURL == "" {
		return
	}

	completionData := map[string]interface{}{
		"task_id":       taskID,
		"success":       success,
		"bdinfo":        bdinfoContent,
		"error_message": errorMessage,
	}

	jsonData, err := json.Marshal(completionData)
	if err != nil {
		fmt.Printf("编码完成数据失败: %v\n", err)
		return
	}

	completionURL := callbackURL + "/complete"
	
	// 创建带超时的HTTP客户端
	client := &http.Client{
		Timeout: 180 * time.Second, // 180秒超时，完成回调可能数据较大
	}
	
	resp, err := client.Post(completionURL, "application/json", strings.NewReader(string(jsonData)))
	if err != nil {
		fmt.Printf("发送完成回调失败: %v\n", err)
		return
	}
	defer resp.Body.Close()
}

// bdinfoHandler 处理BDInfo提取请求
func bdinfoHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSONResponse(w, r, http.StatusMethodNotAllowed, BDInfoResponse{Success: false, Message: "仅支持 POST 方法"})
		return
	}

	var reqData BDInfoRequest
	if err := json.NewDecoder(r.Body).Decode(&reqData); err != nil {
		writeJSONResponse(w, r, http.StatusBadRequest, BDInfoResponse{Success: false, Message: "无效的 JSON 请求体: " + err.Error()})
		return
	}

	remotePath := reqData.RemotePath
	taskID := reqData.TaskID
	callbackURL := reqData.CallbackURL

	if remotePath == "" {
		writeJSONResponse(w, r, http.StatusBadRequest, BDInfoResponse{Success: false, Message: "remote_path 不能为空"})
		return
	}

	if taskID == "" {
		writeJSONResponse(w, r, http.StatusBadRequest, BDInfoResponse{Success: false, Message: "task_id 不能为空"})
		return
	}

	fmt.Printf("BDInfo请求: 开始处理路径 '%s', 任务ID: %s, 回调URL: %s\n", remotePath, taskID, callbackURL)

	if _, err := os.Stat(remotePath); os.IsNotExist(err) {
		fmt.Printf("BDInfo请求: 路径不存在 '%s'\n", remotePath)
		// 更新任务状态为失败
		completeTask(taskID, false, "", fmt.Sprintf("路径不存在: %s", remotePath))
		if callbackURL != "" {
			sendCompletionCallback(callbackURL, taskID, false, "", fmt.Sprintf("路径不存在: %s", remotePath))
		}
		writeJSONResponse(w, r, http.StatusBadRequest, BDInfoResponse{
			Success: false,
			Message: fmt.Sprintf("路径不存在: %s", remotePath),
			TaskID:  taskID,
		})
		return
	}

	// 创建任务记录
	createTask(taskID)

	// 始终使用异步处理模式，支持轮询获取进度
	go func() {
		// 更新初始进度
		updateProgress(taskID, 0, "开始处理", "0s", "估算中...", "running")
		if callbackURL != "" {
			sendProgressCallback(callbackURL, taskID, 0, "开始处理", "0s", "估算中...")
		}
		
		updateProgress(taskID, 5, "初始化BDInfo", "1s", "估算中...", "running")
		if callbackURL != "" {
			sendProgressCallback(callbackURL, taskID, 5, "初始化BDInfo", "1s", "估算中...")
		}
		
		bdinfoContent, err := extractBDInfoWithProgress(remotePath, taskID, callbackURL)
		if err != nil {
			fmt.Printf("BDInfo异步请求: 提取失败 '%s': %v\n", remotePath, err)
			// 更新任务状态为失败
			completeTask(taskID, false, "", fmt.Sprintf("BDInfo提取失败: %v", err))
			if callbackURL != "" {
				sendCompletionCallback(callbackURL, taskID, false, "", fmt.Sprintf("BDInfo提取失败: %v", err))
			}
			return
		}
		fmt.Printf("BDInfo异步请求: 成功提取BDInfo，路径: '%s', 内容长度: %d 字节\n", remotePath, len(bdinfoContent))
		// 更新任务状态为完成
		completeTask(taskID, true, strings.TrimSpace(bdinfoContent), "")
		if callbackURL != "" {
			sendCompletionCallback(callbackURL, taskID, true, strings.TrimSpace(bdinfoContent), "")
		}
	}()
	
	writeJSONResponse(w, r, http.StatusOK, BDInfoResponse{
		Success: true,
		Message: "BDInfo任务已提交，正在异步处理",
		TaskID:  taskID,
	})
}

// RegisterBDInfoRoutes 注册BDInfo相关的路由
func RegisterBDInfoRoutes() {
	http.HandleFunc("/api/media/bdinfo", bdinfoHandler)
	http.HandleFunc("/api/media/bdinfo/progress/", bdinfoProgressHandler)
	fmt.Println("BDInfo路由已注册:")
	fmt.Println("  POST /api/media/bdinfo - BDInfo提取")
	fmt.Println("  GET  /api/media/bdinfo/progress/{task_id} - 进度查询")
}

// BDInfoDataSubstractor 处理 BDInfo 数据，提取关键信息
func BDInfoDataSubstractor(inputFile string) (string, error) {
	if _, err := os.Stat(inputFile); os.IsNotExist(err) {
		return "", fmt.Errorf("输入文件不存在: %s", inputFile)
	}

	substractorPath := "./bdinfo/BDInfoDataSubstractor"
	if _, err := os.Stat(substractorPath); os.IsNotExist(err) {
		return "", fmt.Errorf("BDInfoDataSubstractor 工具不存在: %s", substractorPath)
	}

	cmd := exec.Command(substractorPath, inputFile)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("BDInfoDataSubstractor 执行失败: %v, 输出: %s", err, string(output))
	}

	baseWithoutExt := strings.TrimSuffix(inputFile, filepath.Ext(inputFile))
	outputFile := baseWithoutExt + ".bdinfo.txt"

	if _, err := os.Stat(outputFile); os.IsNotExist(err) {
		content, err := os.ReadFile(inputFile)
		if err != nil {
			return "", fmt.Errorf("无法读取原始文件: %v", err)
		}
		return string(content), nil
	}

	content, err := os.ReadFile(outputFile)
	if err != nil {
		return "", fmt.Errorf("无法读取输出文件: %v", err)
	}

	defer func() {
		os.Remove(outputFile)
		quickSummaryFile := baseWithoutExt + ".quicksummary.txt"
		os.Remove(quickSummaryFile)
	}()

	return string(content), nil
}

// filterEmptyLines 过滤连续3个及以上换行符为2个
func filterEmptyLines(content string) string {
	re := regexp.MustCompile(`\n{3,}`)
	filtered := re.ReplaceAllString(content, "\n\n")

	reColon := regexp.MustCompile(`:\s*\n\s*\n`)
	filtered = reColon.ReplaceAllString(filtered, ":\n")

	return strings.TrimSpace(filtered)
}

// updateProgress 更新任务进度到内存存储
func updateProgress(taskID string, progressPercent float64, currentFile, elapsedTime, remainingTime, status string) {
	progressMutex.Lock()
	defer progressMutex.Unlock()
	
	if task, exists := progressStore[taskID]; exists {
		task.ProgressPercent = progressPercent
		task.CurrentFile = currentFile
		task.ElapsedTime = elapsedTime
		task.RemainingTime = remainingTime
		task.Status = status
	}
}

// updateDiscSize 更新任务的Disc Size
func updateDiscSize(taskID string, discSize int64) {
	progressMutex.Lock()
	defer progressMutex.Unlock()
	
	if task, exists := progressStore[taskID]; exists {
		task.DiscSize = discSize
	}
}

// createTask 创建新任务记录
func createTask(taskID string) {
	progressMutex.Lock()
	defer progressMutex.Unlock()
	
	progressStore[taskID] = &BDInfoTaskStatus{
		TaskID:          taskID,
		ProgressPercent: 0.0,
		CurrentFile:     "初始化",
		ElapsedTime:     "0s",
		RemainingTime:   "估算中...",
		Status:          "running",
		StartTime:       time.Now(),
	}
}

// completeTask 完成任务
func completeTask(taskID string, success bool, bdinfoContent, errorMessage string) {
	progressMutex.Lock()
	defer progressMutex.Unlock()
	
	if task, exists := progressStore[taskID]; exists {
		task.EndTime = time.Now()
		if success {
			task.Status = "completed"
			task.ProgressPercent = 100.0
			task.BDInfoContent = bdinfoContent
		} else {
			task.Status = "failed"
			task.ErrorMessage = errorMessage
		}
	}
}

// getTask 获取任务状态
func getTask(taskID string) (*BDInfoTaskStatus, bool) {
	progressMutex.RLock()
	defer progressMutex.RUnlock()
	
	task, exists := progressStore[taskID]
	return task, exists
}

// bdinfoProgressHandler 处理进度查询请求
func bdinfoProgressHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSONResponse(w, r, http.StatusMethodNotAllowed, BDInfoResponse{Success: false, Message: "仅支持 GET 方法"})
		return
	}

	// 从URL路径中提取taskID
	path := strings.TrimPrefix(r.URL.Path, "/api/media/bdinfo/progress/")
	taskID := strings.TrimSuffix(path, "/")
	
	if taskID == "" {
		writeJSONResponse(w, r, http.StatusBadRequest, BDInfoResponse{Success: false, Message: "task_id 不能为空"})
		return
	}

	task, exists := getTask(taskID)
	if !exists {
		writeJSONResponse(w, r, http.StatusNotFound, BDInfoResponse{Success: false, Message: "任务不存在"})
		return
	}

	// 返回任务状态
	response := map[string]interface{}{
		"success": true,
		"task":    task,
	}
	
	writeJSONResponse(w, r, http.StatusOK, response)
}

// ProcessBDInfo 处理 BDInfo 输出的完整流程
func ProcessBDInfo(inputFile string) (string, error) {
	processedContent, err := BDInfoDataSubstractor(inputFile)
	if err != nil {
		if content, readErr := os.ReadFile(inputFile); readErr == nil {
			processedContent = string(content)
		} else {
			return "", fmt.Errorf("BDInfoDataSubstractor 处理失败且无法读取原始文件: %v", err)
		}
	}
	finalContent := filterEmptyLines(processedContent)
	return finalContent, nil
}
