package repository

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/pt-nexus/server/internal/platform/logx"
	"gorm.io/gorm"
)

type siteSeedRow struct {
	Site                 string   `json:"site"`
	Nickname             string   `json:"nickname"`
	BaseURL              string   `json:"base_url"`
	SpecialTrackerDomain *string  `json:"special_tracker_domain"`
	Group                *string  `json:"group"`
	Description          *string  `json:"description"`
	Passkey              *string  `json:"passkey"`
	Migration            *int     `json:"migration"`
	SpeedLimit           *int     `json:"speed_limit"`
	RatioThreshold       *float64 `json:"ratio_threshold"`
	SeedSpeedLimit       *int     `json:"seed_speed_limit"`
}

type existingSiteRow struct {
	ID             int64   `gorm:"column:id"`
	Site           string  `gorm:"column:site"`
	Nickname       string  `gorm:"column:nickname"`
	BaseURL        string  `gorm:"column:base_url"`
	Description    string  `gorm:"column:description"`
	SpeedLimit     int     `gorm:"column:speed_limit"`
	Passkey        string  `gorm:"column:passkey"`
	RatioThreshold float64 `gorm:"column:ratio_threshold"`
	SeedSpeedLimit int     `gorm:"column:seed_speed_limit"`
}

// SyncSitesFromJSON 将 sites_data.json 的站点元数据同步到 sites 表。
// 参数/返回：jsonPath 为站点 JSON 文件路径；成功返回 nil。
// 失败场景：文件不可读、JSON 格式错误、数据库读写失败。
// 副作用：会对 sites 表执行 INSERT/UPDATE，但会保护用户手动配置（如 cookie/passkey、description）。
func (m *SchemaManager) SyncSitesFromJSON(jsonPath string) error {
	if m.store == nil || m.store.DB == nil {
		return fmt.Errorf("数据库连接未初始化")
	}

	path := strings.TrimSpace(jsonPath)
	if path == "" {
		return fmt.Errorf("sites_data.json 路径为空")
	}

	content, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("读取站点数据文件失败 path=%s err=%w", path, err)
	}

	items := make([]siteSeedRow, 0)
	if err := json.Unmarshal(content, &items); err != nil {
		return fmt.Errorf("解析站点数据失败 path=%s err=%w", path, err)
	}
	if len(items) == 0 {
		logx.Warnf(schemaLogModule, "站点数据为空，跳过同步 path=%s", path)
		return nil
	}

	return m.store.DB.Transaction(func(tx *gorm.DB) error {
		existing := make([]existingSiteRow, 0)
		if err := tx.Raw("SELECT id, site, nickname, base_url, description, speed_limit, passkey, ratio_threshold, seed_speed_limit FROM sites").Scan(&existing).Error; err != nil {
			return fmt.Errorf("读取现有站点失败: %w", err)
		}

		index := map[string]existingSiteRow{}
		for _, row := range existing {
			registerSiteIndex(index, row)
		}

		updated := 0
		added := 0

		for _, item := range items {
			site := strings.TrimSpace(item.Site)
			nickname := strings.TrimSpace(item.Nickname)
			baseURL := strings.TrimSpace(item.BaseURL)
			if site == "" || nickname == "" || baseURL == "" {
				continue
			}

			matched, exists := index[site]
			if !exists {
				if row, ok := index[nickname]; ok {
					matched = row
					exists = true
				} else if row, ok := index[baseURL]; ok {
					matched = row
					exists = true
				}
			}

			// 取 JSON 值（允许为 nil 的字段保持空串）
			jsonGroup := strings.TrimSpace(derefString(item.Group))
			jsonDesc := strings.TrimSpace(derefString(item.Description))
			jsonSpecial := strings.TrimSpace(derefString(item.SpecialTrackerDomain))
			jsonPasskey := strings.TrimSpace(derefString(item.Passkey))
			jsonMigration := derefInt(item.Migration, 0)
			jsonSpeedLimit := derefInt(item.SpeedLimit, 0)
			jsonRatioThreshold := derefFloat(item.RatioThreshold, 0)
			jsonSeedSpeed := derefInt(item.SeedSpeedLimit, -1)

			if exists {
				dbPasskey := strings.TrimSpace(matched.Passkey)
				finalPasskey := dbPasskey
				if finalPasskey == "" && jsonPasskey != "" {
					finalPasskey = jsonPasskey
				}

				finalSpeedLimit := matched.SpeedLimit
				if finalSpeedLimit == 0 && jsonSpeedLimit != 0 {
					finalSpeedLimit = jsonSpeedLimit
				}

				finalRatio := matched.RatioThreshold
				if finalRatio <= 0 {
					if jsonRatioThreshold > 0 {
						finalRatio = jsonRatioThreshold
					} else {
						finalRatio = 3.0
					}
				}

				finalSeedSpeed := matched.SeedSpeedLimit
				if finalSeedSpeed < 0 {
					if jsonSeedSpeed >= 0 {
						finalSeedSpeed = jsonSeedSpeed
					} else {
						finalSeedSpeed = 5
					}
				}

				// description 防覆盖：仅当 JSON 提供值才覆盖，否则保留库里现有值。
				// 避免 JSON 未配置 description 的站点在重同步时把手动维护的值清成 NULL。
				finalDescription := matched.Description
				if jsonDesc != "" {
					finalDescription = jsonDesc
				}

				groupColumn := m.store.GroupColumn()
				updateSQL := fmt.Sprintf(`
					UPDATE sites
					SET site = ?,
						nickname = ?,
						base_url = ?,
						special_tracker_domain = ?,
						%s = ?,
						description = ?,
						passkey = ?,
						migration = ?,
						speed_limit = ?,
						ratio_threshold = ?,
						seed_speed_limit = ?
					WHERE id = ?
				`, groupColumn)

				if err := tx.Exec(
					updateSQL,
					site,
					nickname,
					baseURL,
					nullIfEmpty(jsonSpecial),
					nullIfEmpty(jsonGroup),
					nullIfEmpty(finalDescription),
					nullIfEmpty(finalPasskey),
					jsonMigration,
					finalSpeedLimit,
					finalRatio,
					finalSeedSpeed,
					matched.ID,
				).Error; err != nil {
					return fmt.Errorf("更新站点失败 site=%s err=%w", site, err)
				}
				matched.Site = site
				matched.Nickname = nickname
				matched.BaseURL = baseURL
				matched.Description = finalDescription
				matched.SpeedLimit = finalSpeedLimit
				matched.Passkey = finalPasskey
				matched.RatioThreshold = finalRatio
				matched.SeedSpeedLimit = finalSeedSpeed
				registerSiteIndex(index, matched)
				updated++
				continue
			}

			groupColumn := m.store.GroupColumn()
			insertSQL := fmt.Sprintf(`
				INSERT INTO sites (
					site, nickname, base_url, special_tracker_domain, %s,
					description, passkey, migration, speed_limit, ratio_threshold, seed_speed_limit
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			`, groupColumn)

			ratio := jsonRatioThreshold
			if ratio <= 0 {
				ratio = 3.0
			}
			seedSpeed := jsonSeedSpeed
			if seedSpeed < 0 {
				seedSpeed = 5
			}

			if err := tx.Exec(
				insertSQL,
				site,
				nickname,
				baseURL,
				nullIfEmpty(jsonSpecial),
				nullIfEmpty(jsonGroup),
				nullIfEmpty(jsonDesc),
				nullIfEmpty(jsonPasskey),
				jsonMigration,
				jsonSpeedLimit,
				ratio,
				seedSpeed,
			).Error; err != nil {
				return fmt.Errorf("新增站点失败 site=%s err=%w", site, err)
			}
			inserted := existingSiteRow{}
			if err := tx.Raw(
				"SELECT id, site, nickname, base_url, speed_limit, passkey, ratio_threshold, seed_speed_limit FROM sites WHERE site = ? ORDER BY id DESC LIMIT 1",
				site,
			).Scan(&inserted).Error; err == nil && inserted.ID > 0 {
				registerSiteIndex(index, inserted)
			}
			added++
		}

		logx.Infof(schemaLogModule, "站点同步完成 updated=%d added=%d path=%s", updated, added, path)
		return nil
	})
}

func derefString(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func derefInt(value *int, fallback int) int {
	if value == nil {
		return fallback
	}
	return *value
}

func derefFloat(value *float64, fallback float64) float64 {
	if value == nil {
		return fallback
	}
	return *value
}

func nullIfEmpty(value string) any {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return strings.TrimSpace(value)
}

func registerSiteIndex(index map[string]existingSiteRow, row existingSiteRow) {
	if site := strings.TrimSpace(row.Site); site != "" {
		index[site] = row
	}
	if nickname := strings.TrimSpace(row.Nickname); nickname != "" {
		index[nickname] = row
	}
	if baseURL := strings.TrimSpace(row.BaseURL); baseURL != "" {
		index[baseURL] = row
	}
}
