package config

import (
	"crypto/rand"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"slices"
	"sync"

	"github.com/pt-nexus/server/internal/platform/logx"
)

type Manager struct {
	mu     sync.RWMutex
	path   string
	store  SettingsStore
	config map[string]any
}

// SettingsStore persists the root application settings snapshot.
type SettingsStore interface {
	LoadConfig() (map[string]any, bool, error)
	SaveConfig(configData map[string]any) error
}

func NewManager(paths RuntimePaths) (*Manager, error) {
	manager := &Manager{path: paths.ConfigFile}
	if err := manager.load(); err != nil {
		return nil, err
	}
	return manager, nil
}

func (m *Manager) load() error {
	defaultConfig := defaultConfig()

	_, statErr := os.Stat(m.path)
	if statErr != nil {
		if os.IsNotExist(statErr) {
			m.config = deepCopyMap(defaultConfig)
			return nil
		}
		return fmt.Errorf("read config failed: %w", statErr)
	}

	data, readErr := os.ReadFile(m.path)
	if readErr != nil {
		return fmt.Errorf("read config failed: %w", readErr)
	}

	parsed := map[string]any{}
	if err := json.Unmarshal(data, &parsed); err != nil {
		logx.Warnf("配置", "解析配置文件失败，回退默认配置 err=%v", err)
		m.config = deepCopyMap(defaultConfig)
		return nil
	}

	merged := deepCopyMap(defaultConfig)
	mergeMap(merged, parsed)
	m.config = merged
	return nil
}

func (m *Manager) Get() map[string]any {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return deepCopyMap(m.config)
}

// UseStore switches settings persistence to the configured database store.
func (m *Manager) UseStore(store SettingsStore) error {
	if store == nil {
		return nil
	}

	dbConfig, found, err := store.LoadConfig()
	if err != nil {
		return fmt.Errorf("load database config failed: %w", err)
	}

	m.mu.Lock()
	if found {
		merged := deepCopyMap(defaultConfig())
		mergeMap(merged, dbConfig)
		m.config = merged
	} else {
		m.config = deepCopyMap(m.config)
	}
	m.store = store
	m.ensureAuthBootstrapLocked()
	configToPersist := deepCopyMap(m.config)
	m.mu.Unlock()

	if err := store.SaveConfig(configToPersist); err != nil {
		if found {
			return fmt.Errorf("save merged database config failed: %w", err)
		}
		return fmt.Errorf("import config to database failed: %w", err)
	}
	if !found {
		logx.Infof("配置", "已将文件配置导入数据库")
	}
	return nil
}

func (m *Manager) Save(configData map[string]any) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	configToSave := deepCopyMap(configData)
	if cookieCloud, ok := asMap(configToSave["cookiecloud"]); ok {
		if value, ok := cookieCloud["e2e_password"].(string); ok && value != "" {
			cookieCloud["e2e_password"] = ""
			configToSave["cookiecloud"] = cookieCloud
		}
	}

	content, err := json.MarshalIndent(configToSave, "", "    ")
	if err != nil {
		return fmt.Errorf("marshal config failed: %w", err)
	}

	if m.store != nil {
		if err := m.store.SaveConfig(configToSave); err != nil {
			return fmt.Errorf("write database config failed: %w", err)
		}
		m.config = deepCopyMap(configData)
		return nil
	}

	content = append(content, '\n')
	if err := os.WriteFile(m.path, content, 0o644); err != nil {
		return fmt.Errorf("write config failed: %w", err)
	}

	m.config = deepCopyMap(configData)
	return nil
}

func (m *Manager) ensureAuthBootstrap() {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.ensureAuthBootstrapLocked()
}

func (m *Manager) ensureAuthBootstrapLocked() {
	auth, ok := asMap(m.config["auth"])
	if !ok {
		auth = map[string]any{}
	}
	_, hasHash := auth["password_hash"].(string)
	passwordHash, _ := auth["password_hash"].(string)

	if !hasHash {
		passwordHash = ""
		auth["password_hash"] = ""
	}
	if _, exists := auth["username"]; !exists {
		auth["username"] = "admin"
	}
	if _, exists := auth["must_change_password"]; !exists {
		auth["must_change_password"] = true
	}
	m.config["auth"] = auth

	if passwordHash != "" || os.Getenv("AUTH_PASSWORD_HASH") != "" || os.Getenv("AUTH_PASSWORD") != "" {
		return
	}

	const alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
	generated := make([]byte, 12)
	for idx := range generated {
		rnd, err := rand.Int(rand.Reader, big.NewInt(int64(len(alphabet))))
		if err != nil {
			generated[idx] = alphabet[idx%len(alphabet)]
			continue
		}
		generated[idx] = alphabet[rnd.Int64()]
	}
	_ = os.Setenv("AUTH_PASSWORD", string(generated))
	logx.Infof("启动", "首次启动未检测到密码，已生成临时登录密码 password=%s", string(generated))
}

func defaultConfig() map[string]any {
	return map[string]any{
		"downloaders":            []any{},
		"realtime_speed_enabled": false,
		"downloader_queue": map[string]any{
			"enabled":                         true,
			"max_queue_size":                  1000,
			"max_retries":                     3,
			"max_retry_delay":                 60,
			"max_workers":                     1,
			"queue_monitor_interval":          30,
			"retry_delay_base":                2,
			"task_cleanup_hours":              24,
			"trigger_recent_count_below":      15,
			"trigger_upload_speed_below_mbps": 0,
		},
		"auth": map[string]any{
			"username":             "admin",
			"password_hash":        "",
			"must_change_password": true,
		},
		"cookiecloud": map[string]any{
			"url":          "",
			"key":          "",
			"e2e_password": "",
		},
		"network_proxy": DefaultNetworkProxyConfig().ToMap(),
		"cross_seed": map[string]any{
			"image_hoster":                     "pixhost",
			"screenshot_count":                 3,
			"pixhost_domain":                   "img2.pixhost.cc",
			"agsv_email":                       "",
			"agsv_password":                    "",
			"seedvault_email":                  "",
			"seedvault_password":               "",
			"default_downloader":               "",
			"auto_add_existing_to_downloader":  true,
			"auto_update_existing_torrent":     false,
			"publish_batch_concurrency_mode":   "cpu",
			"publish_batch_concurrency_manual": 5,
			"review_filter":                    "",
		},
		"upload_settings": map[string]any{
			"anonymous_upload":               true,
			"ratio_limiter_interval_seconds": 1800,
		},
		"ui_settings": map[string]any{
			"torrents_view": map[string]any{
				"page_size":   50,
				"sort_prop":   "name",
				"sort_order":  "ascending",
				"name_search": "",
				"active_filters": map[string]any{
					"paths":         []any{},
					"states":        []any{},
					"siteExistence": "all",
					"siteNames":     []any{},
					"downloaderIds": []any{},
				},
			},
			"cross_seed_view": map[string]any{
				"page_size":    20,
				"search_query": "",
				"active_filters": map[string]any{
					"savePath":  "",
					"isDeleted": "",
				},
			},
			"publish_logs_view": map[string]any{
				"page_size":    20,
				"search_query": "",
				"active_filters": map[string]any{
					"status":         "",
					"trigger":        "",
					"scene":          "",
					"queue_group_id": "",
					"target_site":    "",
				},
			},
		},
		"iyuu_settings": map[string]any{
			"path_filter_enabled": false,
			"selected_paths":      []any{},
		},
		"source_priority": []any{},
		"batch_fetch_filters": map[string]any{
			"paths":         []any{},
			"states":        []any{},
			"downloaderIds": []any{},
		},
		"tags_config": map[string]any{
			"category": map[string]any{"enabled": true, "category": ""},
			"tags":     map[string]any{"enabled": true, "tags": []any{"PT Nexus", "\u7ad9\u70b9/{\u7ad9\u70b9\u540d\u79f0}"}},
		},
	}
}

func mergeMap(dst map[string]any, src map[string]any) {
	for key, srcValue := range src {
		if srcMap, ok := asMap(srcValue); ok {
			if dstMap, ok := asMap(dst[key]); ok {
				mergeMap(dstMap, srcMap)
				dst[key] = dstMap
				continue
			}
		}
		dst[key] = srcValue
	}
}

func deepCopyMap(input map[string]any) map[string]any {
	if input == nil {
		return map[string]any{}
	}
	encoded, err := json.Marshal(input)
	if err != nil {
		return map[string]any{}
	}
	copied := map[string]any{}
	if err := json.Unmarshal(encoded, &copied); err != nil {
		return map[string]any{}
	}
	return copied
}

func asMap(value any) (map[string]any, bool) {
	if value == nil {
		return nil, false
	}
	if typed, ok := value.(map[string]any); ok {
		return typed, true
	}
	return nil, false
}

func asSlice(value any) []any {
	if value == nil {
		return []any{}
	}
	if typed, ok := value.([]any); ok {
		return typed
	}
	return []any{}
}

func toString(value any, fallback string) string {
	if str, ok := value.(string); ok {
		return str
	}
	return fallback
}

func containsString(values []string, target string) bool {
	return slices.Contains(values, target)
}
