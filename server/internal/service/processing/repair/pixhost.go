package repair

import (
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	neturl "net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/pt-nexus/server/internal/platform/logx"
)

const maxPosterBytes = 25 * 1024 * 1024
const posterTransferLogModule = "迁移-海报转存"
const posterTransferDownloadRetry = 2
const pixhostOutputDirectHost = "img2.pixhost.cc"
const pixhostUploadAPIURL = "https://api.pixhost.cc/images"

// PixhostUploadConfig 描述 Pixhost 上传 API 与最终直链域名。
type PixhostUploadConfig struct {
	DirectHost   string
	UploadAPIURL string
}

var (
	rePixhostDirect             = regexp.MustCompile(`(\d+)/([^/]+\.(?:jpg|jpeg|png|gif|webp))`)
	rePixhostOgImage            = regexp.MustCompile(`(?is)<meta[^>]+property=["']og:image["'][^>]*content=["']([^"']+)["']`)
	rePixhostImageTag           = regexp.MustCompile(`(?is)<img[^>]+id=["']image["'][^>]*src=["']([^"']+)["']`)
	rePixhostThumbSuffix        = regexp.MustCompile(`_[^.]{1,3}\.(jpg|jpeg|png|gif|webp)$`)
	rePixhostDirectURL          = regexp.MustCompile(`^https://img\d+\.pixhost\.(?:to|cc)/images/\d+/[^/]+\.(jpg|jpeg|png|gif|webp)$`)
	posterTransferProxyPrefixes = []string{
		"http://pt-nexus-proxy.sqing33.dpdns.org/",
		"http://pt-nexus-proxy.1395251710.workers.dev/",
	}
)

// NormalizePosterBBCode 规范化海报字段，统一输出为单个 [img]...[/img]。
func NormalizePosterBBCode(raw string) string {
	return NormalizePosterBBCodeWithConfig(raw, nil)
}

// NormalizePosterBBCodeWithConfig 按 rootConfig 中的 image_hoster 规范化海报字段。
func NormalizePosterBBCodeWithConfig(raw string, rootConfig map[string]any) string {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return ""
	}

	urls := ExtractImageURLsFromText(trimmed)
	if len(urls) == 0 {
		return trimmed
	}
	primary := strings.TrimSpace(urls[0])
	if primary == "" {
		return trimmed
	}

	normalized := NormalizePosterURLWithConfig(primary, rootConfig)
	if normalized == "" {
		normalized = primary
	}
	return "[img]" + normalized + "[/img]"
}

// NormalizePosterURL 对海报 URL 做直链修复，并尽量转存到 Pixhost。
func NormalizePosterURL(raw string) string {
	return NormalizePosterURLWithConfig(raw, nil)
}

// NormalizePosterURLWithConfig 按 rootConfig 中的 image_hoster 对海报 URL 做直链修复并转存。
func NormalizePosterURLWithConfig(raw string, rootConfig map[string]any) string {
	url := strings.TrimSpace(raw)
	if url == "" {
		return ""
	}

	hoster := GetImageHosterFromConfig(rootConfig)
	if hoster == "agsv" {
		return normalizePosterURLForChevereto(url, GetCheveretoConfigFromRootConfig(rootConfig))
	}
	return normalizePosterURLForPixhost(url, GetPixhostUploadConfigFromRootConfig(rootConfig))
}

func normalizePosterURLForChevereto(url string, cfg CheveretoUploadConfig) string {
	if cfg.BaseURL == "" {
		// 没有配置域名，回退到原始 URL
		logx.Warnf(posterTransferLogModule, "末日图床域名未配置，回退原始URL source=%s", CompactLogText(url, 160))
		return url
	}

	token, err := CheveretoLogin(cfg)
	if err != nil {
		logx.Warnf(posterTransferLogModule, "末日图床登录失败，回退原始URL source=%s err=%v", CompactLogText(url, 160), err)
		return url
	}

	transferred, err := TransferRemoteImageToChevereto(url, cfg, token)
	if err != nil || strings.TrimSpace(transferred) == "" {
		if err != nil {
			logx.Warnf(posterTransferLogModule, "海报转存末日图床失败，回退原始URL source=%s err=%v", CompactLogText(url, 160), err)
		} else {
			logx.Warnf(posterTransferLogModule, "海报转存末日图床失败，回退原始URL source=%s err=empty transfer result", CompactLogText(url, 160))
		}
		return url
	}
	logx.Infof(posterTransferLogModule, "海报转存末日图床成功 source=%s target=%s", CompactLogText(url, 160), CompactLogText(transferred, 160))
	return strings.TrimSpace(transferred)
}

func normalizePosterURLForPixhost(url string, cfg PixhostUploadConfig) string {
	lower := strings.ToLower(url)
	if strings.Contains(lower, "pixhost.to") || strings.Contains(lower, "pixhost.cc") {
		if resolved, err := ResolvePixhostImageURLWithConfig(url, cfg); err == nil && strings.TrimSpace(resolved) != "" {
			logx.Infof(posterTransferLogModule, "海报URL已是Pixhost，直链解析成功 source=%s resolved=%s", CompactLogText(url, 160), CompactLogText(resolved, 160))
			return strings.TrimSpace(resolved)
		} else if err != nil {
			logx.Warnf(posterTransferLogModule, "海报URL已是Pixhost但直链解析失败 source=%s err=%v", CompactLogText(url, 160), err)
		}
		if direct := NormalizePixhostDirectHostWithConfig(url, cfg); direct != "" {
			logx.Infof(posterTransferLogModule, "海报URL已是Pixhost，域名规范化完成 source=%s normalized=%s", CompactLogText(url, 160), CompactLogText(direct, 160))
			return direct
		}
		logx.Warnf(posterTransferLogModule, "海报URL已是Pixhost但无法规范化，保留原始URL source=%s", CompactLogText(url, 160))
		return url
	}

	transferred, err := TransferRemoteImageToPixhostWithConfig(url, cfg)
	if err != nil || strings.TrimSpace(transferred) == "" {
		if err != nil {
			logx.Warnf(posterTransferLogModule, "海报转存Pixhost失败，回退原始URL source=%s err=%v", CompactLogText(url, 160), err)
		} else {
			logx.Warnf(posterTransferLogModule, "海报转存Pixhost失败，回退原始URL source=%s err=empty transfer result", CompactLogText(url, 160))
		}
		return url
	}
	logx.Infof(posterTransferLogModule, "海报转存Pixhost成功 source=%s target=%s", CompactLogText(url, 160), CompactLogText(transferred, 160))
	return strings.TrimSpace(transferred)
}

// TransferRemoteImageToPixhost 将远程图片下载后上传到 Pixhost，再返回可用直链。
func TransferRemoteImageToPixhost(imageURL string) (string, error) {
	return TransferRemoteImageToPixhostWithConfig(imageURL, DefaultPixhostUploadConfig())
}

// TransferRemoteImageToPixhostWithConfig 将远程图片下载后上传到 Pixhost，并按配置域名返回直链。
// 参数/返回：imageURL 为远程图片地址；cfg 指定上传 API 与直链域名；成功返回图片直链。
// 失败场景：下载失败、临时文件写入失败、Pixhost 上传失败或返回空链接。
// 副作用：发起 HTTP 请求、写入并删除临时文件，并输出转存日志。
func TransferRemoteImageToPixhostWithConfig(imageURL string, cfg PixhostUploadConfig) (string, error) {
	cfg = normalizePixhostUploadConfig(cfg)
	trimmed := strings.TrimSpace(imageURL)
	if trimmed == "" {
		return "", fmt.Errorf("empty image url")
	}

	candidates := buildPosterDownloadCandidates(trimmed)
	logx.Infof(posterTransferLogModule, "开始海报转存 source=%s candidates=%d", CompactLogText(trimmed, 160), len(candidates))
	errMsgs := make([]string, 0, len(candidates)*posterTransferDownloadRetry)

	for _, candidate := range candidates {
		candidate = strings.TrimSpace(candidate)
		if candidate == "" {
			continue
		}
		for attempt := 1; attempt <= posterTransferDownloadRetry; attempt++ {
			data, contentType, downloadErr := downloadPosterImage(candidate)
			if downloadErr != nil {
				errMsgs = append(errMsgs, fmt.Sprintf("下载失败 candidate=%s attempt=%d err=%v", CompactLogText(candidate, 120), attempt, downloadErr))
				logx.Warnf(posterTransferLogModule, "下载海报失败 candidate=%s attempt=%d/%d err=%v", CompactLogText(candidate, 160), attempt, posterTransferDownloadRetry, downloadErr)
				if attempt < posterTransferDownloadRetry {
					time.Sleep(time.Duration(attempt) * 300 * time.Millisecond)
				}
				continue
			}

			logx.Infof(
				posterTransferLogModule,
				"下载海报成功 candidate=%s attempt=%d bytes=%d content_type=%s",
				CompactLogText(candidate, 160),
				attempt,
				len(data),
				contentType,
			)

			tmpPath, tmpErr := writePosterTempFile(data, contentType)
			if tmpErr != nil {
				errMsgs = append(errMsgs, fmt.Sprintf("落盘失败 candidate=%s err=%v", CompactLogText(candidate, 120), tmpErr))
				logx.Warnf(posterTransferLogModule, "海报临时文件写入失败 candidate=%s err=%v", CompactLogText(candidate, 160), tmpErr)
				continue
			}

			showURL, uploadErr := UploadImageToPixhostWithConfig(tmpPath, cfg)
			_ = os.Remove(tmpPath)
			if uploadErr != nil {
				errMsgs = append(errMsgs, fmt.Sprintf("上传失败 candidate=%s attempt=%d err=%v", CompactLogText(candidate, 120), attempt, uploadErr))
				logx.Warnf(posterTransferLogModule, "上传海报到Pixhost失败 candidate=%s attempt=%d/%d err=%v", CompactLogText(candidate, 160), attempt, posterTransferDownloadRetry, uploadErr)
				if attempt < posterTransferDownloadRetry {
					time.Sleep(time.Duration(attempt) * 300 * time.Millisecond)
				}
				continue
			}

			if resolved, resolveErr := ResolvePixhostImageURLWithConfig(showURL, cfg); resolveErr == nil && strings.TrimSpace(resolved) != "" {
				logx.Infof(posterTransferLogModule, "Pixhost直链解析成功 show_url=%s resolved=%s", CompactLogText(showURL, 160), CompactLogText(resolved, 160))
				return strings.TrimSpace(resolved), nil
			} else if resolveErr != nil {
				logx.Warnf(posterTransferLogModule, "Pixhost直链解析失败 show_url=%s err=%v", CompactLogText(showURL, 160), resolveErr)
			}

			if direct := NormalizePixhostDirectHostWithConfig(showURL, cfg); direct != "" {
				logx.Infof(posterTransferLogModule, "Pixhost直链解析回退成功 show_url=%s direct=%s", CompactLogText(showURL, 160), CompactLogText(direct, 160))
				return direct, nil
			}
			base := strings.TrimSpace(showURL)
			if base == "" {
				errMsgs = append(errMsgs, fmt.Sprintf("Pixhost返回空URL candidate=%s", CompactLogText(candidate, 120)))
				logx.Warnf(posterTransferLogModule, "Pixhost上传返回空URL candidate=%s", CompactLogText(candidate, 160))
				if attempt < posterTransferDownloadRetry {
					time.Sleep(time.Duration(attempt) * 300 * time.Millisecond)
				}
				continue
			}
			logx.Warnf(posterTransferLogModule, "Pixhost返回show_url但未解析为直链，回退show_url show_url=%s", CompactLogText(base, 160))
			return base, nil
		}
	}

	if len(errMsgs) == 0 {
		return "", fmt.Errorf("poster transfer failed without details")
	}
	return "", fmt.Errorf(strings.Join(errMsgs, " | "))
}

func buildPosterDownloadCandidates(imageURL string) []string {
	trimmed := strings.TrimSpace(imageURL)
	if trimmed == "" {
		return []string{}
	}

	candidates := make([]string, 0, 1+len(posterTransferProxyPrefixes))
	seen := map[string]struct{}{}
	appendCandidate := func(url string) {
		item := strings.TrimSpace(url)
		if item == "" {
			return
		}
		if _, exists := seen[item]; exists {
			return
		}
		seen[item] = struct{}{}
		candidates = append(candidates, item)
	}

	appendCandidate(trimmed)
	if isPosterURLProxyWrapped(trimmed) {
		return candidates
	}
	for _, prefix := range posterTransferProxyPrefixes {
		proxyURL := makeProxyWrappedPosterURL(prefix, trimmed)
		appendCandidate(proxyURL)
	}
	return candidates
}

func isPosterURLProxyWrapped(targetURL string) bool {
	trimmed := strings.TrimSpace(targetURL)
	if trimmed == "" {
		return false
	}
	for _, prefix := range posterTransferProxyPrefixes {
		p := strings.TrimSpace(prefix)
		if p == "" {
			continue
		}
		if !strings.HasSuffix(p, "/") {
			p += "/"
		}
		if strings.HasPrefix(trimmed, p) {
			return true
		}
	}
	return false
}

func makeProxyWrappedPosterURL(prefix, targetURL string) string {
	p := strings.TrimSpace(prefix)
	t := strings.TrimSpace(targetURL)
	if p == "" || t == "" {
		return ""
	}
	if !strings.HasSuffix(p, "/") {
		p += "/"
	}
	if strings.HasPrefix(t, p) {
		return t
	}
	return p + t
}

func downloadPosterImage(target string) ([]byte, string, error) {
	trimmed := strings.TrimSpace(target)
	if trimmed == "" {
		return nil, "", fmt.Errorf("empty download url")
	}

	req, err := http.NewRequest(http.MethodGet, trimmed, nil)
	if err != nil {
		return nil, "", err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
	req.Header.Set("Accept", "image/avif,image/webp,image/apng,image/*,*/*;q=0.8")

	client := &http.Client{Timeout: 45 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 400 {
		return nil, "", fmt.Errorf("download poster http %d", resp.StatusCode)
	}

	reader := io.LimitReader(resp.Body, maxPosterBytes+1)
	data, err := io.ReadAll(reader)
	if err != nil {
		return nil, "", err
	}
	if len(data) == 0 {
		return nil, "", fmt.Errorf("empty poster content")
	}
	if len(data) > maxPosterBytes {
		return nil, "", fmt.Errorf("poster too large")
	}

	contentType := strings.ToLower(strings.TrimSpace(resp.Header.Get("Content-Type")))
	if semi := strings.Index(contentType, ";"); semi >= 0 {
		contentType = strings.TrimSpace(contentType[:semi])
	}
	if contentType == "" {
		contentType = strings.ToLower(strings.TrimSpace(http.DetectContentType(data)))
	}
	if !strings.HasPrefix(contentType, "image/") {
		return nil, "", fmt.Errorf("content-type not image: %s", contentType)
	}
	return data, contentType, nil
}

func writePosterTempFile(data []byte, contentType string) (string, error) {
	ext := ".jpg"
	if extensions, extErr := mime.ExtensionsByType(contentType); extErr == nil && len(extensions) > 0 {
		ext = extensions[0]
	}
	if !strings.HasPrefix(ext, ".") {
		ext = "." + ext
	}

	tmpFile, err := os.CreateTemp("", "ptnexus-poster-*"+ext)
	if err != nil {
		return "", err
	}
	tmpPath := tmpFile.Name()
	if _, err := tmpFile.Write(data); err != nil {
		_ = tmpFile.Close()
		_ = os.Remove(tmpPath)
		return "", err
	}
	if err := tmpFile.Close(); err != nil {
		_ = os.Remove(tmpPath)
		return "", err
	}
	return tmpPath, nil
}

// UploadImageToPixhost 上传本地图片到 Pixhost，返回 show_url。
func UploadImageToPixhost(imagePath string) (string, error) {
	return UploadImageToPixhostWithConfig(imagePath, DefaultPixhostUploadConfig())
}

// UploadImageToPixhostWithConfig 上传本地图片到 Pixhost，支持使用配置的 API 域名。
// 参数/返回：imagePath 为本地图片路径；cfg 指定 Pixhost 上传 API；成功返回 show_url。
// 失败场景：文件不存在、网络失败、Pixhost 返回非 200 或响应缺失 show_url。
// 副作用：读取本地文件并发起 HTTP 上传请求。
func UploadImageToPixhostWithConfig(imagePath string, cfg PixhostUploadConfig) (string, error) {
	cfg = normalizePixhostUploadConfig(cfg)
	showURL, _, err := uploadToPixhostDirectStream(imagePath, cfg.UploadAPIURL, func(string, ...any) {})
	return showURL, err
}

// UploadImageToPixhostNarrative 按 Python 版日志风格上传图片到 Pixhost，支持主备域名切换。
// 参数/返回：imagePath 为本地图片路径；成功返回 show_url；失败返回错误。
// 失败场景：文件不存在、网络错误、Pixhost 非 200、响应 JSON 不合法。
// 副作用：读取本地文件并发起 HTTP 请求；会输出叙事式纯文本日志。
func UploadImageToPixhostNarrative(imagePath string) (string, error) {
	return UploadImageToPixhostNarrativeWithLogger(imagePath, logx.PlainInfof)
}

// UploadImageToPixhostNarrativeWithLogger 按 Python 版日志风格上传图片到 Pixhost，支持主备域名切换。
// 参数/返回：logLine 用于输出单行日志（可用于并发场景下的日志缓冲）。
func UploadImageToPixhostNarrativeWithLogger(imagePath string, logLine func(string, ...any)) (string, error) {
	return UploadImageToPixhostNarrativeWithConfigAndLogger(imagePath, DefaultPixhostUploadConfig(), logLine)
}

// UploadImageToPixhostNarrativeWithConfigAndLogger 按配置域名上传图片到 Pixhost，并输出叙事式日志。
// 参数/返回：cfg 指定主备上传 API；logLine 用于输出上传过程；成功返回 show_url。
// 失败场景：本地文件不可读、全部 API 域名请求失败或 Pixhost 响应非法。
// 副作用：读取本地图片并对主备 API 发起 HTTP 请求。
func UploadImageToPixhostNarrativeWithConfigAndLogger(imagePath string, cfg PixhostUploadConfig, logLine func(string, ...any)) (string, error) {
	cfg = normalizePixhostUploadConfig(cfg)
	apiURLs := []string{
		cfg.UploadAPIURL,
		"http://pt-nexus-proxy.sqing33.dpdns.org/" + cfg.UploadAPIURL,
		"http://pt-nexus-proxy.1395251710.workers.dev/" + cfg.UploadAPIURL,
	}

	logLine("准备上传图片: %s", imagePath)
	if _, err := os.Stat(imagePath); err != nil {
		logLine("错误：文件不存在 %s", imagePath)
		return "", err
	}

	maxRetries := 3
	var lastErr error
	for attempt := 1; attempt <= maxRetries; attempt++ {
		for i, apiURL := range apiURLs {
			domainName := "主域名"
			if i != 0 {
				domainName = "备用域名"
			}
			logLine("尝试使用%s: %s", domainName, apiURL)
			showURL, statusCode, err := uploadToPixhostDirectStream(imagePath, apiURL, logLine)
			if err == nil && strings.TrimSpace(showURL) != "" {
				logLine("%s上传成功", domainName)
				return showURL, nil
			}
			lastErr = err
			if statusCode > 0 {
				logLine("   ❌直接上传失败 (状态码: %d)", statusCode)
			} else if err != nil {
				logLine("   ❌直接上传失败: %s", classifyPixhostUploadError(err))
			} else {
				logLine("   ❌直接上传失败")
			}
			logLine("%s上传失败，尝试下一个", domainName)
		}
		if attempt < maxRetries {
			time.Sleep(2 * time.Second)
		}
	}

	logLine("所有API域名都上传失败")
	if lastErr != nil {
		return "", lastErr
	}
	return "", fmt.Errorf("Pixhost 上传失败")
}

func uploadToPixhostDirectStream(imagePath string, apiURL string, logLine func(string, ...any)) (string, int, error) {
	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)

	var (
		writeErr error
		once     sync.Once
	)
	closeWithErr := func(err error) {
		once.Do(func() {
			writeErr = err
			_ = pw.CloseWithError(err)
		})
	}

	go func() {
		defer func() {
			if writeErr == nil {
				_ = pw.Close()
			}
		}()
		defer writer.Close()

		file, err := os.Open(imagePath)
		if err != nil {
			closeWithErr(err)
			return
		}
		defer file.Close()

		part, err := writer.CreateFormFile("img", filepath.Base(imagePath))
		if err != nil {
			closeWithErr(err)
			return
		}
		if _, err := io.Copy(part, file); err != nil {
			closeWithErr(err)
			return
		}
		if err := writer.WriteField("content_type", "0"); err != nil {
			closeWithErr(err)
			return
		}
	}()

	logLine("正在发送上传请求到 Pixhost...")
	req, err := http.NewRequest(http.MethodPost, apiURL, pr)
	if err != nil {
		_ = pr.Close()
		return "", 0, err
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36")

	client := &http.Client{Timeout: 180 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		_ = pr.Close()
		if writeErr != nil {
			return "", 0, writeErr
		}
		return "", 0, err
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", resp.StatusCode, err
	}
	if resp.StatusCode != http.StatusOK {
		return "", resp.StatusCode, fmt.Errorf("Pixhost HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(respBody)))
	}

	parsed := map[string]any{}
	if err := json.Unmarshal(respBody, &parsed); err != nil {
		return "", resp.StatusCode, fmt.Errorf("Pixhost 响应解析失败: %w body=%s", err, CompactLogText(string(respBody), 240))
	}
	showURL := strings.TrimSpace(toStringAny(parsed["show_url"], ""))
	if showURL == "" {
		if dataMap, ok := parsed["data"].(map[string]any); ok {
			showURL = strings.TrimSpace(toStringAny(dataMap["show_url"], ""))
		}
	}
	if showURL == "" {
		return "", resp.StatusCode, fmt.Errorf("Pixhost 未返回 show_url")
	}

	logLine("直接上传成功！图片链接: %s", showURL)
	return showURL, resp.StatusCode, nil
}

func classifyPixhostUploadError(err error) string {
	if err == nil {
		return ""
	}
	text := strings.ToLower(strings.TrimSpace(err.Error()))
	switch {
	case strings.Contains(text, "x509") || strings.Contains(text, "tls") || strings.Contains(text, "certificate"):
		return "SSL连接错误"
	case strings.Contains(text, "timeout") || strings.Contains(text, "i/o timeout") || strings.Contains(text, "context deadline"):
		return "请求超时"
	case strings.Contains(text, "connection reset") || strings.Contains(text, "broken pipe") || strings.Contains(text, "connection refused"):
		return "网络连接被重置"
	default:
		return "网络请求失败"
	}
}

// ResolvePixhostImageURL 将 show_url 解析为可访问的直链 URL。
func ResolvePixhostImageURL(showURL string) (string, error) {
	return ResolvePixhostImageURLWithConfig(showURL, DefaultPixhostUploadConfig())
}

// ResolvePixhostImageURLWithConfig 将 show_url 解析为配置域名下的可访问直链 URL。
// 参数/返回：showURL 为 Pixhost show 页地址；cfg 指定直链域名；成功返回直链，失败返回错误。
func ResolvePixhostImageURLWithConfig(showURL string, cfg PixhostUploadConfig) (string, error) {
	cfg = normalizePixhostUploadConfig(cfg)
	trimmed := strings.TrimSpace(showURL)
	if trimmed == "" {
		return "", fmt.Errorf("empty show_url")
	}

	direct := PixhostShowToDirectURLWithConfig(trimmed, cfg)
	if direct != "" && IsImageURLReachable(direct) {
		return direct, nil
	}

	body, err := FetchPageWithTimeout(trimmed)
	if err == nil && strings.TrimSpace(body) != "" {
		for _, re := range []*regexp.Regexp{rePixhostOgImage, rePixhostImageTag} {
			match := re.FindStringSubmatch(body)
			if len(match) < 2 {
				continue
			}
			candidate := AbsolutizeURL(trimmed, strings.TrimSpace(match[1]))
			if candidate == "" {
				continue
			}
			if isPixhostShowOrThumbURL(candidate) {
				candidate = PixhostShowToDirectURLWithConfig(candidate, cfg)
			}
			candidate = NormalizePixhostDirectHostWithConfig(candidate, cfg)
			if candidate != "" && IsImageURLReachable(candidate) {
				return candidate, nil
			}
		}
	}

	if direct != "" {
		return direct, fmt.Errorf("直链可用性校验失败，返回推算直链")
	}
	return trimmed, fmt.Errorf("无法解析 pixhost 直链，返回 show_url")
}

// PixhostShowToDirectURL 尝试将 pixhost show/th 页面地址转换为图片直链。
func PixhostShowToDirectURL(showURL string) string {
	return PixhostShowToDirectURLWithConfig(showURL, DefaultPixhostUploadConfig())
}

// PixhostShowToDirectURLWithConfig 尝试将 pixhost show/th 地址转换为配置域名下的图片直链。
func PixhostShowToDirectURLWithConfig(showURL string, cfg PixhostUploadConfig) string {
	cfg = normalizePixhostUploadConfig(cfg)
	trimmed := strings.TrimSpace(showURL)
	if trimmed == "" {
		return ""
	}

	direct := trimmed
	if parsed, err := neturl.Parse(trimmed); err == nil && parsed != nil {
		host := strings.ToLower(strings.TrimSpace(parsed.Host))
		path := strings.TrimSpace(parsed.Path)
		for _, prefix := range []string{"/show/", "/th/"} {
			if (host == "pixhost.to" || host == "pixhost.cc") && strings.HasPrefix(path, prefix) {
				parsed.Scheme = "https"
				parsed.Host = cfg.DirectHost
				parsed.Path = "/images/" + strings.TrimPrefix(path, prefix)
				parsed.RawQuery = ""
				parsed.Fragment = ""
				direct = parsed.String()
				break
			}
		}
	}
	direct = rePixhostThumbSuffix.ReplaceAllString(direct, `.$1`)

	if rePixhostDirectURL.MatchString(direct) {
		return NormalizePixhostDirectHostWithConfig(direct, cfg)
	}
	if match := rePixhostDirect.FindStringSubmatch(direct); len(match) >= 3 {
		candidate := fmt.Sprintf("https://%s/images/%s/%s", cfg.DirectHost, match[1], match[2])
		if rePixhostDirectURL.MatchString(candidate) {
			return candidate
		}
	}
	if match := rePixhostDirect.FindStringSubmatch(trimmed); len(match) >= 3 {
		candidate := fmt.Sprintf("https://%s/images/%s/%s", cfg.DirectHost, match[1], match[2])
		if rePixhostDirectURL.MatchString(candidate) {
			return candidate
		}
	}
	return ""
}

// NormalizePixhostDirectHost 规范化 Pixhost 直链域名到 img*.pixhost.to。
func NormalizePixhostDirectHost(value string) string {
	return NormalizePixhostDirectHostWithConfig(value, DefaultPixhostUploadConfig())
}

// NormalizePixhostDirectHostWithConfig 规范化 Pixhost 直链域名到配置的 img*.pixhost.* 主机。
func NormalizePixhostDirectHostWithConfig(value string, cfg PixhostUploadConfig) string {
	cfg = normalizePixhostUploadConfig(cfg)
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return ""
	}
	parsed, err := neturl.Parse(trimmed)
	if err != nil || parsed == nil {
		return ""
	}
	if parsed.Scheme == "" {
		parsed.Scheme = "https"
	}
	host := strings.ToLower(strings.TrimSpace(parsed.Host))
	if strings.HasPrefix(host, "img") && (strings.Contains(host, ".pixhost.to") || strings.Contains(host, ".pixhost.cc")) && strings.Contains(parsed.Path, "/images/") {
		parsed.Host = cfg.DirectHost
		parsed.Scheme = "https"
		return parsed.String()
	}
	if (strings.Contains(host, "pixhost.to") || strings.Contains(host, "pixhost.cc")) && strings.Contains(parsed.Path, "/images/") {
		parsed.Host = cfg.DirectHost
		parsed.Scheme = "https"
		return parsed.String()
	}
	if match := rePixhostDirect.FindStringSubmatch(trimmed); len(match) >= 3 {
		return fmt.Sprintf("https://%s/images/%s/%s", cfg.DirectHost, match[1], match[2])
	}
	return ""
}

// DefaultPixhostUploadConfig 返回兼容旧配置的 Pixhost 默认上传配置。
func DefaultPixhostUploadConfig() PixhostUploadConfig {
	return PixhostUploadConfig{
		DirectHost:   pixhostOutputDirectHost,
		UploadAPIURL: pixhostUploadAPIURL,
	}
}

// GetPixhostUploadConfigFromRootConfig 从 rootConfig 的 cross_seed 节提取 Pixhost 域名配置。
func GetPixhostUploadConfigFromRootConfig(rootConfig map[string]any) PixhostUploadConfig {
	if rootConfig == nil {
		return DefaultPixhostUploadConfig()
	}
	cs, ok := rootConfig["cross_seed"].(map[string]any)
	if !ok {
		return DefaultPixhostUploadConfig()
	}
	return NewPixhostUploadConfig(toStringAny(cs["pixhost_domain"], ""))
}

// NewPixhostUploadConfig 根据用户填写的 Pixhost 域名生成上传 API 与直链域名。
func NewPixhostUploadConfig(domain string) PixhostUploadConfig {
	directHost := normalizePixhostDirectDomain(domain)
	return PixhostUploadConfig{
		DirectHost:   directHost,
		UploadAPIURL: buildPixhostUploadAPIURL(directHost),
	}
}

func normalizePixhostUploadConfig(cfg PixhostUploadConfig) PixhostUploadConfig {
	cfg.DirectHost = normalizePixhostDirectDomain(cfg.DirectHost)
	apiURL := strings.TrimSpace(cfg.UploadAPIURL)
	if apiURL == "" {
		apiURL = buildPixhostUploadAPIURL(cfg.DirectHost)
	}
	cfg.UploadAPIURL = apiURL
	return cfg
}

func normalizePixhostDirectDomain(domain string) string {
	trimmed := strings.TrimSpace(domain)
	if trimmed == "" {
		return pixhostOutputDirectHost
	}
	if parsed, err := neturl.Parse(trimmed); err == nil && parsed != nil && parsed.Host != "" {
		trimmed = parsed.Host
	}
	if i := strings.IndexAny(trimmed, "/?#"); i >= 0 {
		trimmed = trimmed[:i]
	}
	host := strings.ToLower(strings.TrimSpace(trimmed))
	host = strings.TrimPrefix(host, "http://")
	host = strings.TrimPrefix(host, "https://")
	host = strings.Trim(host, ". ")
	if host == "" {
		return pixhostOutputDirectHost
	}
	if strings.HasPrefix(host, "api.") {
		host = "img2." + strings.TrimPrefix(host, "api.")
	}
	if host == "pixhost.to" || host == "pixhost.cc" {
		host = "img2." + host
	}
	return host
}

func buildPixhostUploadAPIURL(directHost string) string {
	host := normalizePixhostDirectDomain(directHost)
	if strings.HasPrefix(host, "api.") {
		return "https://" + host + "/images"
	}
	if strings.HasPrefix(host, "img") {
		if dot := strings.Index(host, "."); dot >= 0 && dot+1 < len(host) {
			root := host[dot+1:]
			if root == "pixhost.to" || root == "pixhost.cc" {
				return "https://api." + root + "/images"
			}
		}
	}
	if host == "pixhost.to" || host == "pixhost.cc" {
		return "https://api." + host + "/images"
	}
	return pixhostUploadAPIURL
}

func isPixhostShowOrThumbURL(value string) bool {
	lower := strings.ToLower(strings.TrimSpace(value))
	return strings.Contains(lower, "pixhost.to/show/") ||
		strings.Contains(lower, "pixhost.to/th/") ||
		strings.Contains(lower, "pixhost.cc/show/") ||
		strings.Contains(lower, "pixhost.cc/th/")
}

// IsImageURLReachable 通过 HEAD/GET 探测 URL 是否可访问且内容类型为图片。
func IsImageURLReachable(target string) bool {
	trimmed := strings.TrimSpace(target)
	if trimmed == "" {
		return false
	}
	client := &http.Client{Timeout: 12 * time.Second}

	headReq, err := http.NewRequest(http.MethodHead, trimmed, nil)
	if err == nil {
		headReq.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
		if resp, headErr := client.Do(headReq); headErr == nil {
			ct := strings.ToLower(strings.TrimSpace(resp.Header.Get("Content-Type")))
			_ = resp.Body.Close()
			if resp.StatusCode >= 200 && resp.StatusCode < 400 && strings.HasPrefix(ct, "image/") {
				return true
			}
		}
	}

	getReq, err := http.NewRequest(http.MethodGet, trimmed, nil)
	if err != nil {
		return false
	}
	getReq.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
	getReq.Header.Set("Range", "bytes=0-32")
	resp, err := client.Do(getReq)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	ct := strings.ToLower(strings.TrimSpace(resp.Header.Get("Content-Type")))
	return resp.StatusCode >= 200 && resp.StatusCode < 400 && strings.HasPrefix(ct, "image/")
}
