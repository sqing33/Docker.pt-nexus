package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	PORT                = "5274"
	SERVER_PORT         = "5275"
	BATCH_ENHANCER_PORT = "5276"
	GITEE_REPO_URL      = "https://gitee.com/sqing33/PTNexus.git"
	GITHUB_REPO_URL     = "https://github.com/sqing33/PTNexus.git"
	UPDATE_DIR          = "/app/data/updates"
	REPO_DIR            = "/app/data/updates/repo"
	REPO_TIMEOUT        = 60 * time.Second // 仓库克隆/拉取超时时间
)

var (
	localConfigFile string
	shanghaiLoc     *time.Location
	// 新增：互斥锁防止重复触发更新
	updateMutex      sync.Mutex
	isSystemUpdating bool
)

func init() {
	if os.Getenv("DEV_ENV") == "true" {
		// 开发环境
		localConfigFile = getEnv("LOCAL_CONFIG_FILE", "/home/sqing/Codes/Docker.pt-nexus-dev/CHANGELOG.json")
	} else {
		// 生产环境
		localConfigFile = getEnv("LOCAL_CONFIG_FILE", "/app/CHANGELOG.json")
	}

	// 初始化时区
	initTimezone()
}

// 初始化时区和定时配置
func initTimezone() {
	var err error
	shanghaiLoc, err = time.LoadLocation("Asia/Shanghai")
	if err != nil {
		log.Printf("警告: 无法加载上海时区: %v，使用UTC时区", err)
		shanghaiLoc = time.UTC
	}
	log.Printf("时区初始化完成: %s", shanghaiLoc.String())

	// 从环境变量读取定时配置
	if getEnv("SCHEDULE_ENABLED", "true") == "false" {
		globalScheduleConfig.Enabled = false
	}
	if scheduleTime := getEnv("SCHEDULE_TIME", "06:00"); scheduleTime != "06:00" {
		globalScheduleConfig.Time = scheduleTime
	}
	if scheduleTimezone := getEnv("SCHEDULE_TIMEZONE", "Asia/Shanghai"); scheduleTimezone != "Asia/Shanghai" {
		globalScheduleConfig.Timezone = scheduleTimezone
		// 重新加载时区
		if loc, err := time.LoadLocation(scheduleTimezone); err == nil {
			shanghaiLoc = loc
			log.Printf("使用自定义时区: %s", scheduleTimezone)
		}
	}

	log.Printf("定时更新配置: enabled=%v, time=%s, timezone=%s",
		globalScheduleConfig.Enabled, globalScheduleConfig.Time, globalScheduleConfig.Timezone)
}

// 获取下一个早上6点的时间
func getNextSixAM() time.Time {
	now := time.Now().In(shanghaiLoc)
	next := time.Date(now.Year(), now.Month(), now.Day(), 6, 0, 0, 0, shanghaiLoc)
	if next.Before(now) {
		next = next.Add(24 * time.Hour)
	}
	return next
}

// 解析时间字符串为时分
func parseTime(timeStr string) (hour, min int, err error) {
	parts := strings.Split(timeStr, ":")
	if len(parts) != 2 {
		return 0, 0, fmt.Errorf("时间格式错误，期望 HH:MM，得到: %s", timeStr)
	}

	hour, err = strconv.Atoi(parts[0])
	if err != nil {
		return 0, 0, fmt.Errorf("小时解析失败: %v", err)
	}

	min, err = strconv.Atoi(parts[1])
	if err != nil {
		return 0, 0, fmt.Errorf("分钟解析失败: %v", err)
	}

	if hour < 0 || hour > 23 || min < 0 || min > 59 {
		return 0, 0, fmt.Errorf("时间值超出范围: %d:%d", hour, min)
	}

	return hour, min, nil
}

// 获取下一个指定时间
func getNextScheduledTime(timeStr string) (time.Time, error) {
	hour, min, err := parseTime(timeStr)
	if err != nil {
		return time.Time{}, err
	}

	now := time.Now().In(shanghaiLoc)
	next := time.Date(now.Year(), now.Month(), now.Day(), hour, min, 0, 0, shanghaiLoc)
	if next.Before(now) {
		next = next.Add(24 * time.Hour)
	}
	return next, nil
}

// 获取更新源配置
func getUpdateSource() string {
	source := strings.ToLower(getEnv("UPDATE_SOURCE", "gitee"))
	if source != "gitee" && source != "github" {
		log.Printf("无效的 UPDATE_SOURCE 值: %s，使用默认值 gitee", source)
		return "gitee"
	}
	return source
}

// 获取仓库 URL
func getRepoURL() string {
	switch getUpdateSource() {
	case "github":
		return GITHUB_REPO_URL
	default:
		return GITEE_REPO_URL
	}
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

type UpdateConfig struct {
	History  []VersionInfo `json:"history"`
	Mappings []DirMapping  `json:"mappings"`
	Preserve []string      `json:"preserve"`
}

type VersionInfo struct {
	Version       string   `json:"version"`
	Date          string   `json:"date"`
	ForceUpdate   bool     `json:"force_update"`
	DisableUpdate bool     `json:"disable_update,omitempty"`
	Changes       []string `json:"changes"`
	Note          string   `json:"note,omitempty"`
}

// 定时更新配置 - 硬编码到Go代码中
type ScheduleConfig struct {
	Enabled  bool       `json:"enabled"`
	Timezone string     `json:"timezone"`
	Time     string     `json:"time"`
	LastRun  *time.Time `json:"last_run"`
}

// 全局定时配置
var globalScheduleConfig = ScheduleConfig{
	Enabled:  true, // 默认启用，可通过环境变量SCHEDULE_ENABLED禁用
	Timezone: "Asia/Shanghai",
	Time:     "06:00",
	LastRun:  nil,
}

type DirMapping struct {
	Source     string   `json:"source"`
	Target     string   `json:"target"`
	Exclude    []string `json:"exclude"`
	Executable bool     `json:"executable"`
}

// 加载定时配置（从全局变量）
func loadScheduleConfig() ScheduleConfig {
	return globalScheduleConfig
}

// 保存定时配置（更新全局变量）
func saveScheduleConfig(now time.Time) {
	// 更新全局配置中的最后执行时间
	globalScheduleConfig.LastRun = &now
	log.Printf("更新定时配置最后执行时间: %s", now.Format("2006-01-02 15:04:05"))
}

// 检查是否应该执行更新
func shouldRunUpdate(now time.Time, schedule ScheduleConfig) bool {
	if !schedule.Enabled {
		return false
	}

	// 解析定时时间
	hour, min, err := parseTime(schedule.Time)
	if err != nil {
		log.Printf("时间配置错误: %v", err)
		return false
	}

	// 检查当前时间是否匹配定时时间
	if now.Hour() != hour || now.Minute() != min {
		return false
	}

	// 检查今天是否已经执行过
	if schedule.LastRun != nil {
		lastRun := schedule.LastRun.In(shanghaiLoc)
		if lastRun.Year() == now.Year() &&
			lastRun.Month() == now.Month() &&
			lastRun.Day() == now.Day() {
			return false
		}
	}

	return true
}

// 更新最后执行时间
func updateLastRunTime(now time.Time) {
	saveScheduleConfig(now)
}

// 执行自动更新
func runAutoUpdate() {
	log.Println("开始执行自动更新检查...")

	localVersion := getLocalVersion()

	// 1. 获取远程配置
	remoteConfig, err := getRemoteConfig()
	if err != nil {
		log.Printf("自动更新失败：无法获取远程配置: %v", err)
		return
	}

	if len(remoteConfig.History) == 0 {
		log.Println("自动更新失败：远程配置为空")
		return
	}

	remoteVersion := remoteConfig.History[0].Version
	shouldForce := remoteConfig.History[0].ForceUpdate
	shouldDisable := remoteConfig.History[0].DisableUpdate

	// 2. 检查是否有新版本
	if !isNewerVersion(remoteVersion, localVersion) {
		log.Printf("本地版本 %s 已是最新，无需更新", localVersion)
		return
	}

	log.Printf("检测到新版本: 本地 %s -> 远程 %s", localVersion, remoteVersion)

	// 3. 检查是否满足自动更新条件
	// 条件：(全局定时更新开启) 或者 (远程标记为强制更新 ForceUpdate)
	// 这里的逻辑是：如果是ForceUpdate，哪怕本地配置可能有其他阻碍，也倾向于执行更新操作
	if !globalScheduleConfig.Enabled && !shouldForce {
		log.Println("定时更新未启用，且非强制更新版本，跳过自动更新")
		return
	}

	// 4. 新增：检查是否禁止更新
	if shouldDisable {
		log.Printf("版本 %s 标记为 disable_update，跳过自动更新", remoteVersion)
		return
	}

	log.Printf("执行更新流程 (强制更新: %v)...", shouldForce)

	// 5. 删除updates目录强制重新拉取
	// 这符合你的要求：如果有更新，先清理旧目录确保干净
	log.Println("清理 updates 目录以强制重新拉取...")
	if err := os.RemoveAll(UPDATE_DIR); err != nil {
		log.Printf("删除updates目录失败: %v", err)
		// 如果删除失败，可能影响后续流程，但尝试继续
	}

	// 确保更新目录存在
	if err := os.MkdirAll(UPDATE_DIR, 0755); err != nil {
		log.Printf("创建更新目录失败: %v", err)
		return
	}

	// 6. 克隆仓库
	log.Println("克隆仓库...")
	if err := cloneRepoWithFallback(); err != nil {
		log.Printf("克隆仓库失败: %v", err)
		return
	}

	// 7. 停止服务
	log.Println("停止服务...")
	stopServices()

	// 8. 备份当前版本
	backupDir := filepath.Join(UPDATE_DIR, "backup")
	os.RemoveAll(backupDir)
	os.MkdirAll(backupDir, 0755)

	// 9. 根据映射同步文件
	// 注意：这里我们使用刚才获取到的 remoteConfig，而不是重新读取文件
	// 虽然克隆了文件，但内存里的 config 是一样的
	log.Println("同步文件...")
	for _, mapping := range remoteConfig.Mappings {
		source := filepath.Join(REPO_DIR, mapping.Source)
		target := mapping.Target

		if err := syncPath(source, target, mapping.Exclude, backupDir); err != nil {
			log.Printf("同步失败: %v", err)
			// 回滚
			rollback(backupDir)
			restartServices()
			return
		}

		// 设置可执行权限
		if mapping.Executable {
			os.Chmod(target, 0755)
		}
	}

	// 10. 更新本地配置文件
	srcConfig := filepath.Join(REPO_DIR, "CHANGELOG.json")
	copyFile(srcConfig, localConfigFile)

	log.Println("重启服务...")
	restartServices()

	log.Printf("自动更新完成: %s", remoteVersion)
}

// 定时检查器
func startScheduledChecker() {
	log.Println("启动定时检查器...")
	ticker := time.NewTicker(1 * time.Minute) // 每分钟检查一次
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			checkAndRunScheduledUpdate()
		}
	}
}

// 检查并执行定时更新
func checkAndRunScheduledUpdate() {
	schedule := loadScheduleConfig()
	now := time.Now().In(shanghaiLoc)

	// 这里只判断时间是否到达，是否真正执行更新在 runAutoUpdate 内部判断
	// 这样可以实现：即使本地把 SCHEDULE_ENABLED 关了，但只要时间到了且远程有 ForceUpdate，依然可以更新

	// 解析定时时间
	hour, min, err := parseTime(schedule.Time)
	if err != nil {
		return
	}

	// 简单的分钟级匹配
	if now.Hour() == hour && now.Minute() == min {
		// 检查今天是否已经执行过
		if schedule.LastRun != nil {
			lastRun := schedule.LastRun.In(shanghaiLoc)
			if lastRun.Year() == now.Year() &&
				lastRun.Month() == now.Month() &&
				lastRun.Day() == now.Day() {
				return
			}
		}

		log.Printf("触发定时检查点 (时区: %s)", now.Format("2006-01-02 15:04:05"))
		// runAutoUpdate 内部会检查 Enabled 状态或 ForceUpdate 状态
		runAutoUpdate()
		updateLastRunTime(now)
	}
}

// 检查是否有跨版本强制更新
func hasCrossVersionForceUpdate(localVersion string, remoteConfig *UpdateConfig) bool {
	if len(remoteConfig.History) == 0 {
		return false
	}

	// 找到本地版本在历史中的位置
	localVersionIndex := -1
	for i, version := range remoteConfig.History {
		if version.Version == localVersion {
			localVersionIndex = i
			break
		}
	}

	// 如果找不到本地版本，检查从最新版本开始的所有版本
	if localVersionIndex == -1 {
		log.Printf("本地版本 %s 在历史记录中未找到，检查所有版本", localVersion)
		for _, version := range remoteConfig.History {
			if version.ForceUpdate {
				log.Printf("发现跨版本强制更新: %s", version.Version)
				return true
			}
		}
		return false
	}

	// 检查从本地版本之后的所有版本
	log.Printf("本地版本 %s 在历史记录中的位置: %d", localVersion, localVersionIndex)
	for i := localVersionIndex - 1; i >= 0; i-- {
		version := remoteConfig.History[i]
		if version.ForceUpdate {
			log.Printf("发现跨版本强制更新: %s (本地版本: %s)", version.Version, localVersion)
			return true
		}
	}

	return false
}

// 检查更新
func checkUpdateHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	// 禁止缓存
	w.Header().Set("Cache-Control", "no-cache, no-store, must-revalidate")
	w.Header().Set("Pragma", "no-cache")
	w.Header().Set("Expires", "0")

	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}

	localVersion := getLocalVersion()

	// 获取远程配置
	remoteConfig, err := getRemoteConfig()
	var remoteVersion string
	var forceUpdate bool
	var disableUpdate bool

	if err != nil {
		log.Printf("检查更新时获取远程配置失败: %v", err)
	} else if len(remoteConfig.History) > 0 {
		remoteVersion = remoteConfig.History[0].Version
		// 修改：检查跨版本强制更新
		forceUpdate = hasCrossVersionForceUpdate(localVersion, remoteConfig)
		disableUpdate = remoteConfig.History[0].DisableUpdate
	}

	hasUpdate := false
	if remoteVersion != "" && localVersion != "" {
		hasUpdate = isNewerVersion(remoteVersion, localVersion)
	}

	if hasUpdate {
		log.Printf("检测到新版本: %s -> %s (Force: %v, Disable: %v)", localVersion, remoteVersion, forceUpdate, disableUpdate)
	}

	// 这里不再做任何自动更新的触发逻辑，只返回数据
	json.NewEncoder(w).Encode(map[string]interface{}{
		"success":        true,
		"has_update":     hasUpdate,
		"local_version":  localVersion,
		"remote_version": remoteVersion,
		"update_control": map[string]interface{}{
			"force_update":   forceUpdate,
			"disable_update": disableUpdate,
			"schedule":       loadScheduleConfig(),
		},
	})
}

// compareVersions 比较两个版本号
// 如果 remote > local 返回 true，否则返回 false
func isNewerVersion(remote, local string) bool {
	// 去除前缀 v 或 V，并去除空格
	remote = strings.TrimSpace(strings.TrimPrefix(strings.ToLower(remote), "v"))
	local = strings.TrimSpace(strings.TrimPrefix(strings.ToLower(local), "v"))

	// 按点分割
	remoteParts := strings.Split(remote, ".")
	localParts := strings.Split(local, ".")

	// 获取最大长度
	maxLen := len(remoteParts)
	if len(localParts) > maxLen {
		maxLen = len(localParts)
	}

	for i := 0; i < maxLen; i++ {
		rVal := 0
		lVal := 0

		// 解析远程版本当前位
		if i < len(remoteParts) {
			rVal, _ = strconv.Atoi(remoteParts[i])
		}

		// 解析本地版本当前位
		if i < len(localParts) {
			lVal, _ = strconv.Atoi(localParts[i])
		}

		// 逐位比较
		if rVal > lVal {
			return true // 远程版本更大
		}
		if rVal < lVal {
			return false // 本地版本更大或已确定不需要更新
		}
		// 如果相等，继续比较下一位
	}

	// 如果所有比较的位都相等，检查版本号长度
	// 例如：3.3.2 vs 3.3，3.3.2 更新
	if len(remoteParts) > len(localParts) {
		// 检查远程版本多出的位是否都是0
		for i := len(localParts); i < len(remoteParts); i++ {
			if val, _ := strconv.Atoi(remoteParts[i]); val != 0 {
				return true // 远程版本有非零的额外位，版本更新
			}
		}
		return false // 远程版本多出的位都是0，版本相同
	}

	return false // 版本完全相同或本地版本更长
}

// 拉取代码
func pullUpdateHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")

	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}

	// 确保更新目录存在
	os.MkdirAll(UPDATE_DIR, 0755)

	if _, err := os.Stat(REPO_DIR); os.IsNotExist(err) {
		// 首次克隆 - 先尝试 Gitee，超时则切换到 GitHub
		log.Println("首次克隆仓库...")
		if err := cloneRepoWithFallback(); err != nil {
			json.NewEncoder(w).Encode(map[string]interface{}{
				"success": false,
				"error":   fmt.Sprintf("克隆仓库失败: %v", err),
			})
			return
		}
	} else {
		// 拉取更新
		log.Println("拉取更新...")
		if err := pullRepoWithFallback(); err != nil {
			json.NewEncoder(w).Encode(map[string]interface{}{
				"success": false,
				"error":   fmt.Sprintf("拉取更新失败: %v", err),
			})
			return
		}
	}

	log.Println("代码拉取成功")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"success": true,
		"message": "代码拉取成功",
	})
}

// 带超时的 git 命令执行
func execGitWithTimeout(timeout time.Duration, args ...string) error {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, "git", args...)
	output, err := cmd.CombinedOutput()

	if ctx.Err() == context.DeadlineExceeded {
		return fmt.Errorf("操作超时")
	}

	if err != nil {
		return fmt.Errorf("%v, 输出: %s", err, output)
	}

	return nil
}

// 克隆仓库，带超时和自动切换
func cloneRepoWithFallback() error {
	primarySource := getUpdateSource()
	var primaryURL, fallbackURL, fallbackSource string

	if primarySource == "github" {
		primaryURL = GITHUB_REPO_URL
		fallbackURL = GITEE_REPO_URL
		fallbackSource = "Gitee"
	} else {
		primaryURL = GITEE_REPO_URL
		fallbackURL = GITHUB_REPO_URL
		fallbackSource = "GitHub"
	}

	log.Printf("尝试从 %s 克隆仓库 (超时时间: %v)...", primarySource, REPO_TIMEOUT)
	err := execGitWithTimeout(REPO_TIMEOUT, "clone", "--depth=1", primaryURL, REPO_DIR)

	if err != nil {
		log.Printf("%s 克隆失败: %v", primarySource, err)
		log.Printf("切换到 %s 仓库...", fallbackSource)

		// 清理可能创建的不完整目录
		os.RemoveAll(REPO_DIR)

		// 尝试从备用仓库克隆
		err = execGitWithTimeout(REPO_TIMEOUT, "clone", "--depth=1", fallbackURL, REPO_DIR)
		if err != nil {
			return fmt.Errorf("%s 克隆也失败: %v", fallbackSource, err)
		}

		log.Printf("已成功从 %s 克隆仓库", fallbackSource)
		return nil
	}

	log.Printf("已成功从 %s 克隆仓库", primarySource)
	return nil
}

// 拉取更新，带超时和自动切换
func pullRepoWithFallback() error {
	// 获取当前远程 URL 以显示来源
	cmd := exec.Command("git", "-C", REPO_DIR, "remote", "get-url", "origin")
	output, err := cmd.Output()
	if err != nil {
		log.Printf("获取远程URL失败，尝试重新设置: %v", err)
		// 如果获取失败，直接重新克隆
		os.RemoveAll(REPO_DIR)
		return cloneRepoWithFallback()
	}

	currentURL := strings.TrimSpace(string(output))
	var repoSource string
	if strings.Contains(currentURL, "gitee.com") {
		repoSource = "Gitee"
	} else if strings.Contains(currentURL, "github.com") {
		repoSource = "GitHub"
	} else {
		repoSource = "未知源"
	}

	// 先尝试当前远程仓库
	log.Printf("正在从 %s 仓库拉取更新 (超时时间: %v)...", repoSource, REPO_TIMEOUT)

	// 尝试多个分支
	branches := []string{"main", "master"}

	for _, branch := range branches {
		log.Printf("尝试 fetch %s 分支...", branch)
		err = execGitWithTimeout(REPO_TIMEOUT, "-C", REPO_DIR, "fetch", "origin", branch)
		if err != nil {
			log.Printf("%s 仓库 %s 分支 fetch 失败: %v", repoSource, branch, err)
			continue
		}

		// Reset
		err = execGitWithTimeout(REPO_TIMEOUT, "-C", REPO_DIR, "reset", "--hard", "origin/"+branch)
		if err != nil {
			log.Printf("%s 仓库 %s 分支 reset 失败: %v", repoSource, branch, err)
			continue
		}

		log.Printf("已成功从 %s 仓库 %s 分支拉取更新", repoSource, branch)
		return nil
	}

	// 所有分支都失败，尝试切换远程仓库
	log.Printf("所有分支都失败，尝试切换远程仓库...")
	if err := switchRemoteRepo(); err != nil {
		return fmt.Errorf("切换远程仓库失败: %v", err)
	}

	// 重新尝试
	return pullRepoWithFallback()
}

// 切换远程仓库地址
func switchRemoteRepo() error {
	// 获取当前远程 URL
	cmd := exec.Command("git", "-C", REPO_DIR, "remote", "get-url", "origin")
	output, err := cmd.Output()
	if err != nil {
		return fmt.Errorf("获取远程 URL 失败: %v", err)
	}

	currentURL := strings.TrimSpace(string(output))
	var newURL, newSource string

	// 根据当前使用的源和配置的优先源来决定切换
	preferredSource := getUpdateSource()

	if strings.Contains(currentURL, "gitee.com") {
		if preferredSource == "gitee" {
			log.Println("当前使用 Gitee，但需要切换到 GitHub...")
			newURL = GITHUB_REPO_URL
			newSource = "GitHub"
		} else {
			log.Println("当前使用 Gitee，按配置切换到 GitHub...")
			newURL = GITHUB_REPO_URL
			newSource = "GitHub"
		}
	} else if strings.Contains(currentURL, "github.com") {
		if preferredSource == "github" {
			log.Println("当前使用 GitHub，但需要切换到 Gitee...")
			newURL = GITEE_REPO_URL
			newSource = "Gitee"
		} else {
			log.Println("当前使用 GitHub，按配置切换到 Gitee...")
			newURL = GITEE_REPO_URL
			newSource = "Gitee"
		}
	} else {
		// 未知源，使用配置的首选源
		log.Printf("当前使用未知源，切换到配置的首选源: %s", preferredSource)
		if preferredSource == "github" {
			newURL = GITHUB_REPO_URL
			newSource = "GitHub"
		} else {
			newURL = GITEE_REPO_URL
			newSource = "Gitee"
		}
	}

	// 设置新的远程 URL
	cmd = exec.Command("git", "-C", REPO_DIR, "remote", "set-url", "origin", newURL)
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("设置远程 URL 失败: %v", err)
	}

	log.Printf("已切换到新的远程仓库: %s (%s)", newURL, newSource)
	return nil
}

// 安装更新
func installUpdateHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")

	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}

	// 读取更新配置
	configFile := filepath.Join(REPO_DIR, "CHANGELOG.json")
	data, err := os.ReadFile(configFile)
	if err != nil {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": false,
			"error":   "无法读取更新配置",
		})
		return
	}

	var config UpdateConfig
	if err := json.Unmarshal(data, &config); err != nil {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": false,
			"error":   "配置解析失败",
		})
		return
	}

	log.Printf("开始安装更新: %s", config.History[0].Version)

	// 检查是否为开发环境
	if os.Getenv("DEV_ENV") == "true" {
		log.Println("【开发环境】执行真实更新流程但不保存文件...")

		// 停止主服务（开发环境也停止以模拟真实情况）
		log.Println("【开发环境】停止服务...")
		stopServices()

		// 创建临时目录用于"下载"文件（但最终会被丢弃）
		tempBackupDir := filepath.Join("/tmp", "pt-nexus-dev-test")
		os.RemoveAll(tempBackupDir)
		os.MkdirAll(tempBackupDir, 0755)

		// 根据映射"同步"文件到临时目录（模拟真实下载过程）
		log.Println("【开发环境】同步文件到临时目录...")
		for _, mapping := range config.Mappings {
			source := filepath.Join(REPO_DIR, mapping.Source)
			// 将目标路径改为临时目录
			tempTarget := filepath.Join(tempBackupDir, mapping.Target)

			if err := syncPathToDev(source, tempTarget, mapping.Exclude); err != nil {
				log.Printf("【开发环境】同步失败: %v", err)
				restartServices()
				json.NewEncoder(w).Encode(map[string]interface{}{
					"success": false,
					"error":   fmt.Sprintf("【开发环境】测试失败: %v", err),
				})
				return
			}
		}

		log.Println("【开发环境】清理临时文件...")
		os.RemoveAll(tempBackupDir)

		log.Println("【开发环境】重启服务...")
		restartServices()

		log.Printf("【开发环境】测试完成: %s (文件已丢弃，未实际修改生产文件)", config.History[0].Version)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": true,
			"message": fmt.Sprintf("【开发环境测试】成功完成更新流程测试（文件未保存）版本: %s", config.History[0].Version),
		})
		return
	}

	// 生产环境：执行实际更新

	// 检查版本是否确实需要更新
	localVersion := getLocalVersion()
	remoteVersion := config.History[0].Version

	// ================== 新增校验开始 ==================
	// 如果配置文件中标记了 disable_update，则拒绝后端更新
	if config.History[0].DisableUpdate {
		log.Printf("版本 %s 标记为 disable_update，拒绝执行热更新", remoteVersion)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": false,
			"error":   "当前版本需要更新 Docker 镜像，无法通过脚本进行热更新，请手动拉取最新镜像。",
		})
		return
	}
	// ================== 新增校验结束 ==================

	if !isNewerVersion(remoteVersion, localVersion) {
		log.Printf("本地版本 %s 已是最新，无需更新", localVersion)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": true,
			"message": fmt.Sprintf("当前版本 %s 已是最新", localVersion),
		})
		return
	}

	log.Printf("开始更新: 本地 %s -> 远程 %s", localVersion, remoteVersion)

	// 停止主服务
	log.Println("停止服务...")
	stopServices()

	// 备份当前版本
	backupDir := filepath.Join(UPDATE_DIR, "backup")
	os.RemoveAll(backupDir)
	os.MkdirAll(backupDir, 0755)

	// 根据映射同步文件
	log.Println("同步文件...")
	for _, mapping := range config.Mappings {
		source := filepath.Join(REPO_DIR, mapping.Source)
		target := mapping.Target

		if err := syncPath(source, target, mapping.Exclude, backupDir); err != nil {
			log.Printf("同步失败: %v", err)
			// 回滚
			rollback(backupDir)
			restartServices()
			json.NewEncoder(w).Encode(map[string]interface{}{
				"success": false,
				"error":   fmt.Sprintf("更新失败: %v", err),
			})
			return
		}

		// 设置可执行权限
		if mapping.Executable {
			os.Chmod(target, 0755)
		}
	}

	// 更新本地配置文件
	srcConfig := filepath.Join(REPO_DIR, "CHANGELOG.json")
	copyFile(srcConfig, localConfigFile)

	log.Println("重启服务...")
	restartServices()

	log.Printf("更新完成: %s", config.History[0].Version)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"success": true,
		"message": fmt.Sprintf("成功更新到 %s", config.History[0].Version),
	})
}

// 同步文件或目录
func syncPath(source, target string, exclude []string, backupDir string) error {
	info, err := os.Stat(source)
	if err != nil {
		return err
	}

	if info.IsDir() {
		return syncDirectory(source, target, exclude, backupDir)
	}
	return syncFile(source, target, backupDir)
}

// 开发环境：同步文件到临时目录（用于测试）
func syncPathToDev(source, target string, exclude []string) error {
	info, err := os.Stat(source)
	if err != nil {
		return err
	}

	if info.IsDir() {
		return syncDirectoryToDev(source, target, exclude)
	}
	return copyFileToDev(source, target)
}

// 开发环境：同步目录到临时位置
func syncDirectoryToDev(source, target string, exclude []string) error {
	return filepath.Walk(source, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}

		// 计算相对路径
		relPath, _ := filepath.Rel(source, path)
		targetPath := filepath.Join(target, relPath)

		if info.IsDir() {
			return os.MkdirAll(targetPath, 0755)
		}

		// 检查是否排除
		if shouldExclude(info.Name(), exclude) {
			return nil
		}

		// 直接复制到临时目录
		return copyFileToDev(path, targetPath)
	})
}

// 开发环境：复制文件到临时位置
func copyFileToDev(src, dst string) error {
	os.MkdirAll(filepath.Dir(dst), 0755)

	sourceFile, err := os.Open(src)
	if err != nil {
		return err
	}
	defer sourceFile.Close()

	destFile, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer destFile.Close()

	_, err = io.Copy(destFile, sourceFile)
	return err
}

// 同步目录
func syncDirectory(source, target string, exclude []string, backupDir string) error {
	return filepath.Walk(source, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}

		// 计算相对路径
		relPath, _ := filepath.Rel(source, path)
		targetPath := filepath.Join(target, relPath)

		if info.IsDir() {
			return os.MkdirAll(targetPath, 0755)
		}

		// 检查是否排除
		if shouldExclude(info.Name(), exclude) {
			return nil
		}

		// 备份原文件
		if _, err := os.Stat(targetPath); err == nil {
			backupPath := filepath.Join(backupDir, strings.TrimPrefix(targetPath, "/"))
			os.MkdirAll(filepath.Dir(backupPath), 0755)
			copyFile(targetPath, backupPath)
		}

		// 复制新文件
		return copyFile(path, targetPath)
	})
}

// 同步单个文件
func syncFile(source, target, backupDir string) error {
	// 备份
	if _, err := os.Stat(target); err == nil {
		backupPath := filepath.Join(backupDir, strings.TrimPrefix(target, "/"))
		os.MkdirAll(filepath.Dir(backupPath), 0755)
		copyFile(target, backupPath)
	}

	// 复制
	os.MkdirAll(filepath.Dir(target), 0755)
	return copyFile(source, target)
}

// 复制文件
func copyFile(src, dst string) error {
	// 如果目标文件存在且是可执行文件，先重命名它
	if info, err := os.Stat(dst); err == nil && info.Mode()&0111 != 0 {
		oldName := dst + ".old"
		os.Remove(oldName) // 删除可能存在的旧备份
		if err := os.Rename(dst, oldName); err != nil {
			log.Printf("警告: 无法重命名文件 %s: %v", dst, err)
		}
		// 延迟删除旧文件
		go func() {
			time.Sleep(5 * time.Second)
			os.Remove(oldName)
		}()
	}

	sourceFile, err := os.Open(src)
	if err != nil {
		return err
	}
	defer sourceFile.Close()

	destFile, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer destFile.Close()

	_, err = io.Copy(destFile, sourceFile)
	return err
}

// 检查是否应该排除
func shouldExclude(name string, patterns []string) bool {
	for _, pattern := range patterns {
		if matched, _ := filepath.Match(pattern, name); matched {
			return true
		}
	}
	return false
}

// 停止服务
func stopServices() {
	if os.Getenv("DEV_ENV") == "true" {
		log.Println("【开发环境】模拟停止服务...")
		time.Sleep(500 * time.Millisecond) // 短暂延迟模拟操作
		log.Println("【开发环境】服务停止完成（模拟）")
		return
	}

	log.Println("正在停止Python服务...")
	exec.Command("pkill", "-TERM", "-f", "python.*app.py").Run()
	time.Sleep(2 * time.Second)

	log.Println("正在停止batch服务...")
	exec.Command("pkill", "-TERM", "batch").Run()
	time.Sleep(2 * time.Second)

	// 如果还在运行，强制停止
	exec.Command("pkill", "-9", "batch").Run()
	time.Sleep(1 * time.Second)

	log.Println("服务已停止")
}

// 重启服务
func restartServices() {
	if os.Getenv("DEV_ENV") == "true" {
		log.Println("【开发环境】模拟重启服务...")
		time.Sleep(500 * time.Millisecond) // 短暂延迟模拟操作
		log.Println("【开发环境】服务重启完成（模拟）")
		return
	}

	cmd := exec.Command("/app/start-services.sh")
	cmd.Start()
}

// 回滚
func rollback(backupDir string) {
	log.Println("回滚更新...")
	filepath.Walk(backupDir, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}
		relPath, _ := filepath.Rel(backupDir, path)
		target := filepath.Join("/", relPath)
		copyFile(path, target)
		return nil
	})
}

// 获取最新版本的禁止更新标志
func getLatestDisableUpdate() bool {
	data, err := os.ReadFile(localConfigFile)
	if err != nil {
		log.Printf("读取本地配置失败: %v", err)
		return false
	}

	var config UpdateConfig
	if err := json.Unmarshal(data, &config); err != nil {
		log.Printf("解析本地配置失败: %v", err)
		return false
	}

	if len(config.History) == 0 {
		return false
	}

	return config.History[0].DisableUpdate
}

// 获取最新版本的强制更新标志
func getLatestForceUpdate() bool {
	data, err := os.ReadFile(localConfigFile)
	if err != nil {
		log.Printf("读取本地配置失败: %v", err)
		return false
	}

	var config UpdateConfig
	if err := json.Unmarshal(data, &config); err != nil {
		log.Printf("解析本地配置失败: %v", err)
		return false
	}

	if len(config.History) == 0 {
		return false
	}

	return config.History[0].ForceUpdate
}

// 获取本地版本
func getLocalVersion() string {
	data, err := os.ReadFile(localConfigFile)
	if err != nil {
		log.Printf("读取本地配置失败: %v", err)
		return "unknown"
	}

	var config UpdateConfig
	if err := json.Unmarshal(data, &config); err != nil {
		log.Printf("解析本地配置失败: %v", err)
		return "unknown"
	}

	return config.History[0].Version
}

// 新增辅助函数：获取远程配置结构体
func getRemoteConfig() (*UpdateConfig, error) {
	var baseURL string
	switch getUpdateSource() {
	case "github":
		// GitHub raw链接
		baseURL = "https://raw.githubusercontent.com/sqing33/PTNexus/main/CHANGELOG.json"
	default:
		// Gitee raw链接
		baseURL = "https://gitee.com/sqing33/PTNexus/raw/main/CHANGELOG.json"
	}

	// 【修复】：添加随机时间戳参数，强制不使用缓存
	// 这样每次请求都会被服务器视为新的请求，确保获取到最新的 disable_update 状态
	requestURL := fmt.Sprintf("%s?t=%d", baseURL, time.Now().UnixNano())

	// 创建不使用代理的 HTTP 客户端
	client := &http.Client{
		Timeout: 10 * time.Second,
		Transport: &http.Transport{
			Proxy: func(req *http.Request) (*url.URL, error) {
				return nil, nil // 不使用代理
			},
		},
	}

	log.Printf("正在请求远程配置: %s", requestURL) // 打印请求地址方便调试
	resp, err := client.Get(requestURL)
	if err != nil {
		return nil, fmt.Errorf("获取远程配置失败: %v", err)
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("读取远程配置失败: %v", err)
	}

	var config UpdateConfig
	if err := json.Unmarshal(data, &config); err != nil {
		return nil, fmt.Errorf("解析远程配置失败: %v", err)
	}

	return &config, nil
}

// 获取远程版本
func getRemoteVersion() string {
	config, err := getRemoteConfig()
	if err != nil {
		log.Printf("获取远程配置失败: %v", err)
		return ""
	}

	if len(config.History) == 0 {
		return ""
	}

	return config.History[0].Version
}

// 健康检查
func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":  "healthy",
		"service": "pt-nexus-updater",
		"time":    time.Now().Format(time.RFC3339),
	})
}

// 获取更新日志
func getChangelogHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")

	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}

	// 根据环境变量选择更新源
	var baseURL string
	switch getUpdateSource() {
	case "github":
		baseURL = "https://raw.githubusercontent.com/sqing33/PTNexus/main/CHANGELOG.json"
	default:
		baseURL = "https://gitee.com/sqing33/PTNexus/raw/main/CHANGELOG.json"
	}

	log.Printf("正在从 %s 获取更新日志", getUpdateSource())

	resp, err := http.Get(baseURL)
	if err != nil {
		log.Printf("获取远程配置失败: %v", err)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success":   false,
			"changelog": []string{},
		})
		return
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Printf("读取远程配置失败: %v", err)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success":   false,
			"changelog": []string{},
		})
		return
	}

	var config UpdateConfig
	if err := json.Unmarshal(data, &config); err != nil {
		log.Printf("解析远程配置失败: %v", err)
		log.Printf("尝试解析的数据: %s", string(data))
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success":   false,
			"changelog": []string{},
		})
		return
	}

	log.Printf("解析成功，history 长度: %d", len(config.History))
	if len(config.History) > 0 {
		log.Printf("最新版本: %s, 更新内容数量: %d", config.History[0].Version, len(config.History[0].Changes))
		for i, change := range config.History[0].Changes {
			log.Printf("更新内容 %d: %s", i+1, change)
		}
	}

	// 检查 history 是否为空
	if len(config.History) == 0 {
		log.Printf("远程 CHANGELOG.json 中 history 数组为空")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success":   false,
			"changelog": []string{},
		})
		return
	}

	json.NewEncoder(w).Encode(map[string]interface{}{
		"success":   true,
		"changelog": config.History[0].Changes,
		"history":   config.History,
	})
}

// 代理到服务器
func proxyToServer(w http.ResponseWriter, r *http.Request) {
	targetURL, _ := url.Parse("http://localhost:" + SERVER_PORT)
	proxy := httputil.NewSingleHostReverseProxy(targetURL)

	originalDirector := proxy.Director
	proxy.Director = func(req *http.Request) {
		originalDirector(req)
		req.Host = targetURL.Host
		req.URL.Host = targetURL.Host
		req.URL.Scheme = targetURL.Scheme
	}

	// 设置 CORS
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")

	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}

	proxy.ServeHTTP(w, r)
}

// 代理到 batch
func proxyToBatchEnhancer(w http.ResponseWriter, r *http.Request) {
	targetURL, _ := url.Parse("http://localhost:" + BATCH_ENHANCER_PORT)
	proxy := httputil.NewSingleHostReverseProxy(targetURL)

	// 设置Director来修改请求
	originalDirector := proxy.Director
	proxy.Director = func(req *http.Request) {
		originalDirector(req)
		req.Host = targetURL.Host
		req.URL.Host = targetURL.Host
		req.URL.Scheme = targetURL.Scheme
	}

	// 设置 CORS
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")

	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}

	proxy.ServeHTTP(w, r)
}

func main() {
	log.Println("PT Nexus 更新器启动...")
	log.Println("监听端口:", PORT)
	log.Printf("配置的更新源: %s", getUpdateSource())

	// 检查定时配置
	schedule := loadScheduleConfig()
	if schedule.Enabled {
		log.Printf("定时更新已启用，时间: %s (%s)", schedule.Time, schedule.Timezone)
		log.Println("更新方式: 定时检查 + 手动触发")
		// 启动定时检查器
		go startScheduledChecker()
	} else {
		log.Println("更新方式: 手动触发")
		log.Printf("定时更新已禁用，可通过环境变量SCHEDULE_ENABLED=true启用")
	}

	// 注册路由
	http.HandleFunc("/health", healthHandler)
	http.HandleFunc("/update/check", checkUpdateHandler)
	http.HandleFunc("/update/pull", pullUpdateHandler)
	http.HandleFunc("/update/install", installUpdateHandler)
	http.HandleFunc("/update/changelog", getChangelogHandler)

	// 代理路由
	http.Handle("/batch-enhance/", http.HandlerFunc(proxyToBatchEnhancer))
	http.Handle("/records", http.HandlerFunc(proxyToBatchEnhancer))
	http.Handle("/", http.HandlerFunc(proxyToServer))

	// 启动 HTTP 服务器
	log.Fatal(http.ListenAndServe(":"+PORT, nil))
}
