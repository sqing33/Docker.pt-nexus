package main

import (
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
	"strings"
	"time"
)

const (
	PORT                = "5274"
	SERVER_PORT         = "5275"
	BATCH_ENHANCER_PORT = "5276"
	REPO_URL            = "https://github.com/sqing33/Docker.pt-nexus.git"
	UPDATE_DIR          = "/app/data/updates"
	REPO_DIR            = "/app/data/updates/repo"
)

var (
	localConfigFile string
)

func init() {
	if os.Getenv("DEV_ENV") == "true" {
		// 开发环境
		localConfigFile = getEnv("LOCAL_CONFIG_FILE", "/root/Code/Docker.pt-nexus-dev/update_mapping.json")
	} else {
		// 生产环境
		localConfigFile = getEnv("LOCAL_CONFIG_FILE", "/app/update_mapping.json")
	}
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

type UpdateConfig struct {
	Version   string       `json:"version"`
	Changelog []string     `json:"changelog"`
	Mappings  []DirMapping `json:"mappings"`
	Preserve  []string     `json:"preserve"`
}

type DirMapping struct {
	Source     string   `json:"source"`
	Target     string   `json:"target"`
	Exclude    []string `json:"exclude"`
	Executable bool     `json:"executable"`
}

// 检查更新
func checkUpdateHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")

	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}

	localVersion := getLocalVersion()
	remoteVersion := getRemoteVersion()

	hasUpdate := false
	if remoteVersion != "" && localVersion != "" {
		localVer := strings.TrimPrefix(localVersion, "v")
		remoteVer := strings.TrimPrefix(remoteVersion, "v")
		hasUpdate = remoteVer != localVer
	}

	json.NewEncoder(w).Encode(map[string]interface{}{
		"success":        true,
		"has_update":     hasUpdate,
		"local_version":  localVersion,
		"remote_version": remoteVersion,
	})
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

	var cmd *exec.Cmd
	if _, err := os.Stat(REPO_DIR); os.IsNotExist(err) {
		// 首次克隆
		log.Println("克隆仓库...")
		cmd = exec.Command("git", "clone", "--depth=1", REPO_URL, REPO_DIR)
	} else {
		// 拉取更新
		log.Println("拉取更新...")
		fetchCmd := exec.Command("git", "-C", REPO_DIR, "fetch", "origin", "main")
		if output, err := fetchCmd.CombinedOutput(); err != nil {
			log.Printf("Git fetch失败: %v, 输出: %s", err, output)
			json.NewEncoder(w).Encode(map[string]interface{}{
				"success": false,
				"error":   fmt.Sprintf("Git fetch失败: %v", err),
			})
			return
		}
		cmd = exec.Command("git", "-C", REPO_DIR, "reset", "--hard", "origin/main")
	}

	output, err := cmd.CombinedOutput()
	if err != nil {
		log.Printf("Git操作失败: %v, 输出: %s", err, output)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": false,
			"error":   fmt.Sprintf("Git操作失败: %v", err),
		})
		return
	}

	log.Println("代码拉取成功")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"success": true,
		"message": "代码拉取成功",
	})
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
	configFile := filepath.Join(REPO_DIR, "update_mapping.json")
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

	log.Printf("开始安装更新: %s", config.Version)

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
	srcConfig := filepath.Join(REPO_DIR, "update_mapping.json")
	copyFile(srcConfig, localConfigFile)

	log.Println("重启服务...")
	restartServices()

	log.Printf("更新完成: %s", config.Version)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"success": true,
		"message": fmt.Sprintf("成功更新到 %s", config.Version),
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

	return config.Version
}

// 获取远程版本
func getRemoteVersion() string {
	url := "https://raw.githubusercontent.com/sqing33/Docker.pt-nexus/main/update_mapping.json"
	resp, err := http.Get(url)
	if err != nil {
		log.Printf("获取远程配置失败: %v", err)
		return ""
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Printf("读取远程配置失败: %v", err)
		return ""
	}

	var config UpdateConfig
	if err := json.Unmarshal(data, &config); err != nil {
		log.Printf("解析远程配置失败: %v", err)
		return ""
	}

	return config.Version
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

	// 从远程 update_mapping.json 获取 changelog
	url := "https://raw.githubusercontent.com/sqing33/Docker.pt-nexus/main/update_mapping.json"
	resp, err := http.Get(url)
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
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success":   false,
			"changelog": []string{},
		})
		return
	}

	json.NewEncoder(w).Encode(map[string]interface{}{
		"success":   true,
		"changelog": config.Changelog,
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
	log.Println("更新方式: 手动触发")

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
