package repository

import (
	"fmt"
	"strings"

	"github.com/pt-nexus/server/internal/platform/logx"
)

const schemaLogModule = "数据库初始化"

type schemaColumnSpec struct {
	name       string
	definition map[string]string
}

type schemaIndexSpec struct {
	table   string
	name    string
	columns []string
}

// SchemaManager 负责初始化数据库核心表结构并补齐缺失列。
// 参数/返回：依赖 Store 访问数据库，初始化方法返回 error 表示失败原因。
// 失败场景：数据库连接异常、DDL 执行失败、信息模式查询失败。
// 副作用：会创建表、添加缺失列、创建索引并写入初始化日志。
type SchemaManager struct {
	store *Store
}

// NewSchemaManager 创建数据库结构管理器实例。
// 参数/返回：store 为数据库连接容器，返回可复用的结构管理器。
// 失败场景：无直接失败场景。
// 副作用：无副作用，仅构造对象。
func NewSchemaManager(store *Store) *SchemaManager {
	return &SchemaManager{store: store}
}

// EnsureSchema 确保核心业务表与关键字段存在，避免接口因缺表缺列返回 500。
// 参数/返回：无参数，成功返回 nil，失败返回详细错误。
// 失败场景：建表 SQL 执行失败、补列失败、索引创建失败。
// 副作用：会执行 CREATE TABLE、ALTER TABLE、CREATE INDEX。
func (m *SchemaManager) EnsureSchema() error {
	if m.store == nil || m.store.DB == nil {
		return fmt.Errorf("数据库连接未初始化")
	}

	logx.Infof(schemaLogModule, "开始校验数据库结构 db_type=%s", m.store.DBType)

	for _, sqlText := range m.createTableSQLs() {
		if err := m.store.DB.Exec(sqlText).Error; err != nil {
			return fmt.Errorf("创建核心表失败: %w", err)
		}
	}

	if m.store.DBType == "mysql" {
		if err := m.createAutoSeedMySQLTables(); err != nil {
			return err
		}
		if err := m.ensureTableColumns("auto_seed_rules", m.columnSpecs()["auto_seed_rules"]); err != nil {
			return err
		}
		if err := m.ensureTableColumns("auto_seed_items", m.columnSpecs()["auto_seed_items"]); err != nil {
			return err
		}
		if err := m.fixAutoSeedMySQLColumnTypes(); err != nil {
			return err
		}
	} else {
		if err := m.store.DB.AutoMigrate(&AutoSeedRule{}, &AutoSeedItem{}); err != nil {
			return fmt.Errorf("创建自动发种表失败: %w", err)
		}
	}

	for tableName, columns := range m.columnSpecs() {
		if err := m.ensureTableColumns(tableName, columns); err != nil {
			return err
		}
	}

	if err := m.migratePublishTriggerColumns(); err != nil {
		return err
	}

	for _, index := range m.indexSpecs() {
		if err := m.ensureIndex(index); err != nil {
			return err
		}
	}

	// 迁移阶段：修复 seed_parameters 表中 removed_ardtudeclarations 列的类型
	// 旧版本该列可能为 VARCHAR(255)，导致长数据写入失败
	if err := m.fixSeedParametersColumnTypes(); err != nil {
		return err
	}
	if err := m.backfillSeedParameterLastPublishAtFromPublishLogs(); err != nil {
		logx.Warnf(schemaLogModule, "回填 seed_parameters.last_publish_at 失败 err=%v", err)
	}

	logx.Infof(schemaLogModule, "数据库结构校验完成 db_type=%s", m.store.DBType)
	return nil
}

// lastPublishAtEmptyCondition 返回判断 last_publish_at 为空的 WHERE 片段。
// MySQL/PostgreSQL 中该列为日期类型，与空串比较会触发 1525 错误，仅 SQLite(TEXT) 需要判空串。
func (m *SchemaManager) lastPublishAtEmptyCondition() string {
	if m.store.DBType == "sqlite" {
		return "(last_publish_at IS NULL OR last_publish_at = '')"
	}
	return "last_publish_at IS NULL"
}

// backfillSeedParameterLastPublishAtFromPublishLogs 使用成功发布日志补齐空的最后发布时间。
// 参数/返回：无入参，返回数据库查询或更新错误。
// 失败场景：publish_logs 查询失败或 seed_parameters 更新失败时返回错误。
// 副作用：仅更新 last_publish_at 为空的 seed_parameters 记录。
func (m *SchemaManager) backfillSeedParameterLastPublishAtFromPublishLogs() error {
	if m == nil || m.store == nil || m.store.DB == nil {
		return nil
	}

	rows := make([]PublishLogEntry, 0)
	if err := m.store.DB.Model(&PublishLogEntry{}).
		Select("torrent_id, source_site, title, created_at, updated_at").
		Where("status IN ?", []string{"success", "edited", "exists"}).
		Find(&rows).Error; err != nil {
		return err
	}
	if len(rows) == 0 {
		return nil
	}

	type latestRow struct {
		torrentID string
		source    string
		title     string
		publishAt string
	}
	latestByKey := make(map[string]latestRow)
	latestByTitle := make(map[string]latestRow)
	for _, row := range rows {
		torrentID := strings.TrimSpace(row.TorrentID)
		source := strings.TrimSpace(row.SourceSite)
		title := strings.TrimSpace(row.Title)
		publishAt := strings.TrimSpace(row.UpdatedAt)
		if publishAt == "" {
			publishAt = strings.TrimSpace(row.CreatedAt)
		}
		if publishAt == "" {
			continue
		}
		if torrentID != "" && source != "" {
			key := strings.ToLower(torrentID) + "\x00" + strings.ToLower(source)
			if current, ok := latestByKey[key]; !ok || publishAt > current.publishAt {
				latestByKey[key] = latestRow{torrentID: torrentID, source: source, title: title, publishAt: publishAt}
			}
		}
		if title != "" {
			key := strings.ToLower(title)
			if current, ok := latestByTitle[key]; !ok || publishAt > current.publishAt {
				latestByTitle[key] = latestRow{torrentID: torrentID, source: source, title: title, publishAt: publishAt}
			}
		}
	}

	for _, row := range latestByKey {
		loweredSource := strings.ToLower(row.source)
		result := m.store.DB.Table("seed_parameters").
			Where("torrent_id = ? AND (site_name = ? OR nickname = ? OR LOWER(TRIM(site_name)) = ? OR LOWER(TRIM(nickname)) = ?)", row.torrentID, row.source, row.source, loweredSource, loweredSource).
			Where(m.lastPublishAtEmptyCondition()).
			Updates(map[string]any{"last_publish_at": row.publishAt})
		if result.Error != nil {
			return result.Error
		}
	}
	for _, row := range latestByTitle {
		result := m.store.DB.Table("seed_parameters").
			Where("LOWER(TRIM(name)) = LOWER(TRIM(?))", row.title).
			Where(m.lastPublishAtEmptyCondition()).
			Updates(map[string]any{"last_publish_at": row.publishAt})
		if result.Error != nil {
			return result.Error
		}
	}
	return nil
}

func (m *SchemaManager) migratePublishTriggerColumns() error {
	if m == nil || m.store == nil || m.store.DB == nil {
		return nil
	}

	type migrationSpec struct {
		table string
	}
	specs := []migrationSpec{
		{table: "publish_queue_tasks"},
		{table: "publish_logs"},
	}

	oldColumn := "trigger"
	newColumn := "publish_trigger"

	quotedOld := oldColumn
	switch strings.ToLower(strings.TrimSpace(m.store.DBType)) {
	case "mysql":
		quotedOld = "`" + oldColumn + "`"
	case "postgresql":
		quotedOld = `"` + oldColumn + `"`
	default:
		quotedOld = oldColumn
	}

	for _, spec := range specs {
		columnSet, err := m.listColumnSet(spec.table)
		if err != nil {
			return err
		}
		_, hasOld := columnSet[oldColumn]
		_, hasNew := columnSet[newColumn]
		if !hasOld || !hasNew {
			continue
		}

		sqlText := fmt.Sprintf(
			"UPDATE %s SET %s = %s WHERE (%s IS NULL OR %s = '') AND %s IS NOT NULL AND %s <> ''",
			spec.table,
			newColumn,
			quotedOld,
			newColumn,
			newColumn,
			quotedOld,
			quotedOld,
		)
		if err := m.store.DB.Exec(sqlText).Error; err != nil {
			return fmt.Errorf("迁移触发字段失败 table=%s err=%w", spec.table, err)
		}
	}
	return nil
}

func (m *SchemaManager) createTableSQLs() []string {
	switch m.store.DBType {
	case "mysql":
		return []string{
			`CREATE TABLE IF NOT EXISTS traffic_stats (
				stat_datetime DATETIME NOT NULL,
				downloader_id VARCHAR(64) NOT NULL,
				uploaded BIGINT DEFAULT 0,
				downloaded BIGINT DEFAULT 0,
				upload_speed BIGINT DEFAULT 0,
				download_speed BIGINT DEFAULT 0,
				cumulative_uploaded BIGINT NOT NULL DEFAULT 0,
				cumulative_downloaded BIGINT NOT NULL DEFAULT 0,
				PRIMARY KEY (stat_datetime, downloader_id)
			) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
			`CREATE TABLE IF NOT EXISTS traffic_stats_hourly (
				stat_datetime DATETIME NOT NULL,
				downloader_id VARCHAR(64) NOT NULL,
				uploaded BIGINT DEFAULT 0,
				downloaded BIGINT DEFAULT 0,
				avg_upload_speed BIGINT DEFAULT 0,
				avg_download_speed BIGINT DEFAULT 0,
				samples INTEGER DEFAULT 0,
				cumulative_uploaded BIGINT NOT NULL DEFAULT 0,
				cumulative_downloaded BIGINT NOT NULL DEFAULT 0,
				PRIMARY KEY (stat_datetime, downloader_id)
			) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
			`CREATE TABLE IF NOT EXISTS torrents (
				hash VARCHAR(64) NOT NULL,
				name TEXT NOT NULL,
				save_path TEXT,
				size BIGINT,
				progress DOUBLE,
				state VARCHAR(50),
				sites VARCHAR(255),
				` + "`group`" + ` VARCHAR(255),
				official_site VARCHAR(255),
				details TEXT,
				downloader_id VARCHAR(64) NOT NULL,
				last_seen DATETIME NOT NULL,
				iyuu_last_check DATETIME NULL,
				seeders INT DEFAULT 0,
				is_hidden TINYINT(1) NOT NULL DEFAULT 0,
				hidden_reason VARCHAR(64) NULL,
				hidden_at DATETIME NULL,
				PRIMARY KEY (hash, downloader_id)
			) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
			`CREATE TABLE IF NOT EXISTS torrent_upload_stats (
				hash VARCHAR(64) NOT NULL,
				downloader_id VARCHAR(64) NOT NULL,
				uploaded BIGINT DEFAULT 0,
				is_hidden TINYINT(1) NOT NULL DEFAULT 0,
				hidden_reason VARCHAR(64) NULL,
				hidden_at DATETIME NULL,
				PRIMARY KEY (hash, downloader_id)
			) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
			`CREATE TABLE IF NOT EXISTS sites (
				id BIGINT NOT NULL AUTO_INCREMENT,
				site VARCHAR(255) UNIQUE DEFAULT NULL,
				nickname VARCHAR(255) DEFAULT NULL,
				base_url VARCHAR(255) DEFAULT NULL,
				special_tracker_domain VARCHAR(255) DEFAULT NULL,
				` + "`group`" + ` VARCHAR(255) DEFAULT NULL,
				description VARCHAR(255) DEFAULT NULL,
				cookie TEXT DEFAULT NULL,
				passkey TEXT DEFAULT NULL,
				migration INT NOT NULL DEFAULT 1,
				speed_limit INT NOT NULL DEFAULT 0,
				ratio_threshold DOUBLE NOT NULL DEFAULT 3.0,
				seed_speed_limit INT NOT NULL DEFAULT 5,
				can_publish TINYINT(1) NOT NULL DEFAULT 1,
				forbidden_transfer_sites LONGTEXT,
				sort_order INT NOT NULL DEFAULT 0,
				PRIMARY KEY (id)
			) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
			`CREATE TABLE IF NOT EXISTS app_settings (
				setting_key VARCHAR(64) NOT NULL,
				value_json LONGTEXT NOT NULL,
				created_at DATETIME NOT NULL,
				updated_at DATETIME NOT NULL,
				PRIMARY KEY (setting_key)
			) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
			`CREATE TABLE IF NOT EXISTS seed_parameters (
				hash VARCHAR(64) NOT NULL,
				torrent_id VARCHAR(255) NOT NULL,
				site_name VARCHAR(255) NOT NULL,
				nickname VARCHAR(255),
				name TEXT,
				title TEXT,
				subtitle TEXT,
				imdb_link TEXT,
				douban_link TEXT,
				tmdb_link TEXT,
				type VARCHAR(100),
				medium VARCHAR(100),
				video_codec VARCHAR(100),
				audio_codec VARCHAR(100),
				resolution VARCHAR(100),
				team VARCHAR(100),
				official_site VARCHAR(255),
				source VARCHAR(100),
				tags TEXT,
				poster TEXT,
				screenshots TEXT,
				screenshot_review_status VARCHAR(20) NOT NULL DEFAULT 'none',
				statement TEXT,
				body TEXT,
				mediainfo TEXT,
				title_components TEXT,
				removed_ardtudeclarations TEXT,
				is_reviewed TINYINT(1) NOT NULL DEFAULT 0,
				mediainfo_status VARCHAR(20) DEFAULT 'pending',
				bdinfo_task_id VARCHAR(36),
				bdinfo_started_at DATETIME,
				bdinfo_completed_at DATETIME,
				bdinfo_error TEXT,
				publish_at DATETIME NULL,
				last_publish_at DATETIME NULL,
				created_at DATETIME NOT NULL,
				updated_at DATETIME NOT NULL,
				PRIMARY KEY (hash, torrent_id, site_name)
			) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
			`CREATE TABLE IF NOT EXISTS publish_queue_tasks (
				id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
				group_id VARCHAR(64) NOT NULL,
				status VARCHAR(32) NOT NULL,
				task_id VARCHAR(64),
				publish_trigger VARCHAR(32) NOT NULL DEFAULT 'queue',
				scene VARCHAR(32),
				source_site VARCHAR(255),
				torrent_id VARCHAR(255),
				target_site VARCHAR(255),
				downloader_id VARCHAR(64),
				title TEXT,
				subtitle TEXT,
				payload_json LONGTEXT NOT NULL,
				upload_data_json LONGTEXT NOT NULL,
				context_json LONGTEXT NOT NULL,
				attempt_count INT NOT NULL DEFAULT 0,
				scheduled_at DATETIME NULL,
				next_run_at DATETIME NULL,
				started_at DATETIME NULL,
				finished_at DATETIME NULL,
				last_error LONGTEXT,
				last_result LONGTEXT,
				created_at DATETIME NOT NULL,
				updated_at DATETIME NOT NULL
			) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
			`CREATE TABLE IF NOT EXISTS publish_logs (
				id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
				publish_trigger VARCHAR(32) NOT NULL,
				scene VARCHAR(32),
				queue_task_id BIGINT NULL,
				queue_group_id VARCHAR(64),
				task_id VARCHAR(64),
				torrent_id VARCHAR(255),
				source_site VARCHAR(255),
				target_site VARCHAR(255),
				downloader_id VARCHAR(64),
				title TEXT,
				subtitle TEXT,
				status VARCHAR(32) NOT NULL,
				result_url LONGTEXT,
				logs LONGTEXT,
				auto_add_result LONGTEXT,
				cost_ms BIGINT NOT NULL DEFAULT 0,
				created_at DATETIME NOT NULL,
				updated_at DATETIME NOT NULL
			) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
			`CREATE TABLE IF NOT EXISTS resource_info (
				id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
				title TEXT,
				year VARCHAR(16),
				country VARCHAR(255),
				douban_id VARCHAR(64),
				imdb_id VARCHAR(64),
				tmdb_id VARCHAR(64),
			poster_url LONGTEXT,
			summary LONGTEXT,
			screenshots LONGTEXT,
			created_at DATETIME NOT NULL,
			updated_at DATETIME NOT NULL
		) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
			`CREATE TABLE IF NOT EXISTS scheduled_seed_tasks (
				id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
				name VARCHAR(128) NOT NULL,
				status VARCHAR(16) NOT NULL DEFAULT 'active',
				seeds_json LONGTEXT NOT NULL,
				target_sites_json LONGTEXT NOT NULL,
				interval_minutes INT NOT NULL,
				current_seed_index INT NOT NULL DEFAULT 0,
				current_site_index INT NOT NULL DEFAULT 0,
				total_published INT NOT NULL DEFAULT 0,
				total_skipped INT NOT NULL DEFAULT 0,
				loop_enabled TINYINT(1) NOT NULL DEFAULT 0,
				trigger_tag VARCHAR(64) NOT NULL,
				last_run_at DATETIME NULL,
				next_run_at DATETIME NOT NULL,
				created_at DATETIME NOT NULL,
				updated_at DATETIME NOT NULL
			) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
		}
	case "postgresql":
		return []string{
			`CREATE TABLE IF NOT EXISTS traffic_stats (
				stat_datetime TIMESTAMP NOT NULL,
				downloader_id VARCHAR(64) NOT NULL,
				uploaded BIGINT DEFAULT 0,
				downloaded BIGINT DEFAULT 0,
				upload_speed BIGINT DEFAULT 0,
				download_speed BIGINT DEFAULT 0,
				cumulative_uploaded BIGINT NOT NULL DEFAULT 0,
				cumulative_downloaded BIGINT NOT NULL DEFAULT 0,
				PRIMARY KEY (stat_datetime, downloader_id)
			)`,
			`CREATE TABLE IF NOT EXISTS traffic_stats_hourly (
				stat_datetime TIMESTAMP NOT NULL,
				downloader_id VARCHAR(64) NOT NULL,
				uploaded BIGINT DEFAULT 0,
				downloaded BIGINT DEFAULT 0,
				avg_upload_speed BIGINT DEFAULT 0,
				avg_download_speed BIGINT DEFAULT 0,
				samples INTEGER DEFAULT 0,
				cumulative_uploaded BIGINT NOT NULL DEFAULT 0,
				cumulative_downloaded BIGINT NOT NULL DEFAULT 0,
				PRIMARY KEY (stat_datetime, downloader_id)
			)`,
			`CREATE TABLE IF NOT EXISTS torrents (
				hash VARCHAR(64) NOT NULL,
				name TEXT NOT NULL,
				save_path TEXT,
				size BIGINT,
				progress DOUBLE PRECISION,
				state VARCHAR(50),
				sites VARCHAR(255),
				"group" VARCHAR(255),
				official_site VARCHAR(255),
				details TEXT,
				downloader_id VARCHAR(64) NOT NULL,
				last_seen TIMESTAMP NOT NULL,
				iyuu_last_check TIMESTAMP NULL,
				seeders INTEGER DEFAULT 0,
				is_hidden INTEGER NOT NULL DEFAULT 0,
				hidden_reason VARCHAR(64),
				hidden_at TIMESTAMP NULL,
				PRIMARY KEY (hash, downloader_id)
			)`,
			`CREATE TABLE IF NOT EXISTS torrent_upload_stats (
				hash VARCHAR(64) NOT NULL,
				downloader_id VARCHAR(64) NOT NULL,
				uploaded BIGINT DEFAULT 0,
				is_hidden INTEGER NOT NULL DEFAULT 0,
				hidden_reason VARCHAR(64),
				hidden_at TIMESTAMP NULL,
				PRIMARY KEY (hash, downloader_id)
			)`,
			`CREATE TABLE IF NOT EXISTS sites (
				id BIGSERIAL PRIMARY KEY,
				site VARCHAR(255) UNIQUE,
				nickname VARCHAR(255),
				base_url VARCHAR(255),
				special_tracker_domain VARCHAR(255),
				"group" VARCHAR(255),
				description VARCHAR(255),
				cookie TEXT,
				passkey TEXT,
				migration INTEGER NOT NULL DEFAULT 1,
				speed_limit INTEGER NOT NULL DEFAULT 0,
				ratio_threshold DOUBLE PRECISION NOT NULL DEFAULT 3.0,
				seed_speed_limit INTEGER NOT NULL DEFAULT 5,
				can_publish INTEGER NOT NULL DEFAULT 1,
				forbidden_transfer_sites TEXT,
				sort_order INTEGER NOT NULL DEFAULT 0
			)`,
			`CREATE TABLE IF NOT EXISTS app_settings (
				setting_key VARCHAR(64) PRIMARY KEY,
				value_json TEXT NOT NULL,
				created_at TIMESTAMP NOT NULL,
				updated_at TIMESTAMP NOT NULL
			)`,
			`CREATE TABLE IF NOT EXISTS seed_parameters (
				hash VARCHAR(64) NOT NULL,
				torrent_id VARCHAR(255) NOT NULL,
				site_name VARCHAR(255) NOT NULL,
				nickname VARCHAR(255),
				name TEXT,
				title TEXT,
				subtitle TEXT,
				imdb_link TEXT,
				douban_link TEXT,
				tmdb_link TEXT,
				type VARCHAR(100),
				medium VARCHAR(100),
				video_codec VARCHAR(100),
				audio_codec VARCHAR(100),
				resolution VARCHAR(100),
				team VARCHAR(100),
				official_site VARCHAR(255),
				source VARCHAR(100),
				tags TEXT,
				poster TEXT,
				screenshots TEXT,
				screenshot_review_status VARCHAR(20) NOT NULL DEFAULT 'none',
				statement TEXT,
				body TEXT,
				mediainfo TEXT,
				title_components TEXT,
				removed_ardtudeclarations TEXT,
				is_reviewed BOOLEAN NOT NULL DEFAULT FALSE,
				mediainfo_status VARCHAR(20) DEFAULT 'pending',
				bdinfo_task_id VARCHAR(36),
				bdinfo_started_at TIMESTAMP,
				bdinfo_completed_at TIMESTAMP,
				bdinfo_error TEXT,
				publish_at TIMESTAMP NULL,
				last_publish_at TIMESTAMP NULL,
				created_at TIMESTAMP NOT NULL,
				updated_at TIMESTAMP NOT NULL,
				PRIMARY KEY (hash, torrent_id, site_name)
			)`,
			`CREATE TABLE IF NOT EXISTS publish_queue_tasks (
				id BIGSERIAL PRIMARY KEY,
				group_id VARCHAR(64) NOT NULL,
				status VARCHAR(32) NOT NULL,
				task_id VARCHAR(64),
				publish_trigger VARCHAR(32) NOT NULL DEFAULT 'queue',
				scene VARCHAR(32),
				source_site VARCHAR(255),
				torrent_id VARCHAR(255),
				target_site VARCHAR(255),
				downloader_id VARCHAR(64),
				title TEXT,
				subtitle TEXT,
				payload_json TEXT NOT NULL,
				upload_data_json TEXT NOT NULL,
				context_json TEXT NOT NULL,
				attempt_count INTEGER NOT NULL DEFAULT 0,
				scheduled_at TIMESTAMP NULL,
				next_run_at TIMESTAMP NULL,
				started_at TIMESTAMP NULL,
				finished_at TIMESTAMP NULL,
				last_error TEXT,
				last_result TEXT,
				created_at TIMESTAMP NOT NULL,
				updated_at TIMESTAMP NOT NULL
			)`,
			`CREATE TABLE IF NOT EXISTS publish_logs (
				id BIGSERIAL PRIMARY KEY,
				publish_trigger VARCHAR(32) NOT NULL,
				scene VARCHAR(32),
				queue_task_id BIGINT NULL,
				queue_group_id VARCHAR(64),
				task_id VARCHAR(64),
				torrent_id VARCHAR(255),
				source_site VARCHAR(255),
				target_site VARCHAR(255),
				downloader_id VARCHAR(64),
				title TEXT,
				subtitle TEXT,
				status VARCHAR(32) NOT NULL,
				result_url TEXT,
				logs TEXT,
				auto_add_result TEXT,
				cost_ms BIGINT NOT NULL DEFAULT 0,
				created_at TIMESTAMP NOT NULL,
				updated_at TIMESTAMP NOT NULL
			)`,
			`CREATE TABLE IF NOT EXISTS resource_info (
				id BIGSERIAL PRIMARY KEY,
				title TEXT,
				year VARCHAR(16),
				country VARCHAR(255),
				douban_id VARCHAR(64),
				imdb_id VARCHAR(64),
				tmdb_id VARCHAR(64),
			poster_url TEXT,
			summary TEXT,
			screenshots TEXT,
			created_at TIMESTAMP NOT NULL,
			updated_at TIMESTAMP NOT NULL
		)`,
			`CREATE TABLE IF NOT EXISTS scheduled_seed_tasks (
				id BIGSERIAL PRIMARY KEY,
				name VARCHAR(128) NOT NULL,
				status VARCHAR(16) NOT NULL DEFAULT 'active',
				seeds_json TEXT NOT NULL,
				target_sites_json TEXT NOT NULL,
				interval_minutes INTEGER NOT NULL,
				current_seed_index INTEGER NOT NULL DEFAULT 0,
				current_site_index INTEGER NOT NULL DEFAULT 0,
				total_published INTEGER NOT NULL DEFAULT 0,
				total_skipped INTEGER NOT NULL DEFAULT 0,
				loop_enabled BOOLEAN NOT NULL DEFAULT FALSE,
				trigger_tag VARCHAR(64) NOT NULL,
				last_run_at TIMESTAMP NULL,
				next_run_at TIMESTAMP NOT NULL,
				created_at TIMESTAMP NOT NULL,
				updated_at TIMESTAMP NOT NULL
			)`,
		}
	default:
		return []string{
			`CREATE TABLE IF NOT EXISTS traffic_stats (
				stat_datetime TEXT NOT NULL,
				downloader_id TEXT NOT NULL,
				uploaded INTEGER DEFAULT 0,
				downloaded INTEGER DEFAULT 0,
				upload_speed INTEGER DEFAULT 0,
				download_speed INTEGER DEFAULT 0,
				cumulative_uploaded INTEGER NOT NULL DEFAULT 0,
				cumulative_downloaded INTEGER NOT NULL DEFAULT 0,
				PRIMARY KEY (stat_datetime, downloader_id)
			)`,
			`CREATE TABLE IF NOT EXISTS traffic_stats_hourly (
				stat_datetime TEXT NOT NULL,
				downloader_id TEXT NOT NULL,
				uploaded INTEGER DEFAULT 0,
				downloaded INTEGER DEFAULT 0,
				avg_upload_speed INTEGER DEFAULT 0,
				avg_download_speed INTEGER DEFAULT 0,
				samples INTEGER DEFAULT 0,
				cumulative_uploaded INTEGER NOT NULL DEFAULT 0,
				cumulative_downloaded INTEGER NOT NULL DEFAULT 0,
				PRIMARY KEY (stat_datetime, downloader_id)
			)`,
			`CREATE TABLE IF NOT EXISTS torrents (
				hash TEXT NOT NULL,
				name TEXT NOT NULL,
				save_path TEXT,
				size INTEGER,
				progress REAL,
				state TEXT,
				sites TEXT,
				` + "`group`" + ` TEXT,
				official_site TEXT,
				details TEXT,
				downloader_id TEXT NOT NULL,
				last_seen TEXT NOT NULL,
				iyuu_last_check TEXT NULL,
				seeders INTEGER DEFAULT 0,
				is_hidden INTEGER NOT NULL DEFAULT 0,
				hidden_reason TEXT,
				hidden_at TEXT NULL,
				PRIMARY KEY (hash, downloader_id)
			)`,
			`CREATE TABLE IF NOT EXISTS torrent_upload_stats (
				hash TEXT NOT NULL,
				downloader_id TEXT NOT NULL,
				uploaded INTEGER DEFAULT 0,
				is_hidden INTEGER NOT NULL DEFAULT 0,
				hidden_reason TEXT,
				hidden_at TEXT NULL,
				PRIMARY KEY (hash, downloader_id)
			)`,
			`CREATE TABLE IF NOT EXISTS sites (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				site TEXT UNIQUE,
				nickname TEXT,
				base_url TEXT,
				special_tracker_domain TEXT,
				` + "`group`" + ` TEXT,
				description TEXT,
				cookie TEXT,
				passkey TEXT,
				migration INTEGER NOT NULL DEFAULT 1,
				speed_limit INTEGER NOT NULL DEFAULT 0,
				ratio_threshold REAL NOT NULL DEFAULT 3.0,
				seed_speed_limit INTEGER NOT NULL DEFAULT 5,
				can_publish INTEGER NOT NULL DEFAULT 1,
				forbidden_transfer_sites TEXT,
				sort_order INTEGER NOT NULL DEFAULT 0
			)`,
			`CREATE TABLE IF NOT EXISTS app_settings (
				setting_key TEXT PRIMARY KEY,
				value_json TEXT NOT NULL,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)`,
			`CREATE TABLE IF NOT EXISTS seed_parameters (
				hash TEXT NOT NULL,
				torrent_id TEXT NOT NULL,
				site_name TEXT NOT NULL,
				nickname TEXT,
				name TEXT,
				title TEXT,
				subtitle TEXT,
				imdb_link TEXT,
				douban_link TEXT,
				tmdb_link TEXT,
				type TEXT,
				medium TEXT,
				video_codec TEXT,
				audio_codec TEXT,
				resolution TEXT,
				team TEXT,
				official_site TEXT,
				source TEXT,
				tags TEXT,
				poster TEXT,
				screenshots TEXT,
				screenshot_review_status TEXT NOT NULL DEFAULT 'none',
				statement TEXT,
				body TEXT,
				mediainfo TEXT,
				title_components TEXT,
				removed_ardtudeclarations TEXT,
				is_reviewed INTEGER NOT NULL DEFAULT 0,
				mediainfo_status TEXT DEFAULT 'pending',
				bdinfo_task_id TEXT,
				bdinfo_started_at TEXT,
				bdinfo_completed_at TEXT,
				bdinfo_error TEXT,
				publish_at TEXT NULL,
				last_publish_at TEXT NULL,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL,
				PRIMARY KEY (hash, torrent_id, site_name)
			)`,
			`CREATE TABLE IF NOT EXISTS publish_queue_tasks (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				group_id TEXT NOT NULL,
				status TEXT NOT NULL,
				task_id TEXT,
				publish_trigger TEXT NOT NULL DEFAULT 'queue',
				scene TEXT,
				source_site TEXT,
				torrent_id TEXT,
				target_site TEXT,
				downloader_id TEXT,
				title TEXT,
				subtitle TEXT,
				payload_json TEXT NOT NULL,
				upload_data_json TEXT NOT NULL,
				context_json TEXT NOT NULL,
				attempt_count INTEGER NOT NULL DEFAULT 0,
				scheduled_at TEXT NULL,
				next_run_at TEXT NULL,
				started_at TEXT NULL,
				finished_at TEXT NULL,
				last_error TEXT,
				last_result TEXT,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)`,
			`CREATE TABLE IF NOT EXISTS publish_logs (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				publish_trigger TEXT NOT NULL,
				scene TEXT,
				queue_task_id INTEGER NULL,
				queue_group_id TEXT,
				task_id TEXT,
				torrent_id TEXT,
				source_site TEXT,
				target_site TEXT,
				downloader_id TEXT,
				title TEXT,
				subtitle TEXT,
				status TEXT NOT NULL,
				result_url TEXT,
				logs TEXT,
				auto_add_result TEXT,
				cost_ms INTEGER NOT NULL DEFAULT 0,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)`,
			`CREATE TABLE IF NOT EXISTS resource_info (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				title TEXT,
				year TEXT,
				country TEXT,
				douban_id TEXT,
				imdb_id TEXT,
				tmdb_id TEXT,
			poster_url TEXT,
			summary TEXT,
			screenshots TEXT,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		)`,
			`CREATE TABLE IF NOT EXISTS scheduled_seed_tasks (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				status TEXT NOT NULL DEFAULT 'active',
				seeds_json TEXT NOT NULL,
				target_sites_json TEXT NOT NULL,
				interval_minutes INTEGER NOT NULL,
				current_seed_index INTEGER NOT NULL DEFAULT 0,
				current_site_index INTEGER NOT NULL DEFAULT 0,
				total_published INTEGER NOT NULL DEFAULT 0,
				total_skipped INTEGER NOT NULL DEFAULT 0,
				loop_enabled INTEGER NOT NULL DEFAULT 0,
				trigger_tag TEXT NOT NULL,
				last_run_at TEXT NULL,
				next_run_at TEXT NOT NULL,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)`,
		}
	}
}

func (m *SchemaManager) columnSpecs() map[string][]schemaColumnSpec {
	return map[string][]schemaColumnSpec{
		"traffic_stats": {
			{name: "stat_datetime", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
			{name: "downloader_id", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(64) NOT NULL", "postgresql": "VARCHAR(64) NOT NULL"}},
			{name: "uploaded", definition: map[string]string{"sqlite": "INTEGER DEFAULT 0", "mysql": "BIGINT DEFAULT 0", "postgresql": "BIGINT DEFAULT 0"}},
			{name: "downloaded", definition: map[string]string{"sqlite": "INTEGER DEFAULT 0", "mysql": "BIGINT DEFAULT 0", "postgresql": "BIGINT DEFAULT 0"}},
			{name: "upload_speed", definition: map[string]string{"sqlite": "INTEGER DEFAULT 0", "mysql": "BIGINT DEFAULT 0", "postgresql": "BIGINT DEFAULT 0"}},
			{name: "download_speed", definition: map[string]string{"sqlite": "INTEGER DEFAULT 0", "mysql": "BIGINT DEFAULT 0", "postgresql": "BIGINT DEFAULT 0"}},
			{name: "cumulative_uploaded", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "BIGINT NOT NULL DEFAULT 0", "postgresql": "BIGINT NOT NULL DEFAULT 0"}},
			{name: "cumulative_downloaded", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "BIGINT NOT NULL DEFAULT 0", "postgresql": "BIGINT NOT NULL DEFAULT 0"}},
		},
		"traffic_stats_hourly": {
			{name: "stat_datetime", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
			{name: "downloader_id", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(64) NOT NULL", "postgresql": "VARCHAR(64) NOT NULL"}},
			{name: "uploaded", definition: map[string]string{"sqlite": "INTEGER DEFAULT 0", "mysql": "BIGINT DEFAULT 0", "postgresql": "BIGINT DEFAULT 0"}},
			{name: "downloaded", definition: map[string]string{"sqlite": "INTEGER DEFAULT 0", "mysql": "BIGINT DEFAULT 0", "postgresql": "BIGINT DEFAULT 0"}},
			{name: "avg_upload_speed", definition: map[string]string{"sqlite": "INTEGER DEFAULT 0", "mysql": "BIGINT DEFAULT 0", "postgresql": "BIGINT DEFAULT 0"}},
			{name: "avg_download_speed", definition: map[string]string{"sqlite": "INTEGER DEFAULT 0", "mysql": "BIGINT DEFAULT 0", "postgresql": "BIGINT DEFAULT 0"}},
			{name: "samples", definition: map[string]string{"sqlite": "INTEGER DEFAULT 0", "mysql": "INTEGER DEFAULT 0", "postgresql": "INTEGER DEFAULT 0"}},
			{name: "cumulative_uploaded", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "BIGINT NOT NULL DEFAULT 0", "postgresql": "BIGINT NOT NULL DEFAULT 0"}},
			{name: "cumulative_downloaded", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "BIGINT NOT NULL DEFAULT 0", "postgresql": "BIGINT NOT NULL DEFAULT 0"}},
		},
		"auto_seed_rules": {
			{name: "seed_retention_minutes", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "INT NOT NULL DEFAULT 0", "postgresql": "INTEGER NOT NULL DEFAULT 0"}},
			{name: "download_url", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
		},
		"auto_seed_items": {
			{name: "rule_id", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "BIGINT NOT NULL DEFAULT 0", "postgresql": "BIGINT NOT NULL DEFAULT 0"}},
			{name: "source_site", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "guid", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "torrent_url", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "detail_url", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "name", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "subtitle", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "size_bytes", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "BIGINT NOT NULL DEFAULT 0", "postgresql": "BIGINT NOT NULL DEFAULT 0"}},
			{name: "resource_type", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(32)", "postgresql": "VARCHAR(32)"}},
			{name: "medium", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "tags_json", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "status", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(32)", "postgresql": "VARCHAR(32)"}},
			{name: "reject_reason", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "publish_results_json", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "downloader_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "downloader_hash", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "progress", definition: map[string]string{"sqlite": "REAL NOT NULL DEFAULT 0", "mysql": "DOUBLE NOT NULL DEFAULT 0", "postgresql": "DOUBLE PRECISION NOT NULL DEFAULT 0"}},
			{name: "downloaded", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "TINYINT(1) NOT NULL DEFAULT 0", "postgresql": "BOOLEAN NOT NULL DEFAULT FALSE"}},
			{name: "torrent_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "site_name", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "pushed_at", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
			{name: "organized_at", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
			{name: "published_at", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
			{name: "created_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
			{name: "updated_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
		},
		"torrents": {
			{name: "hash", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(64) NOT NULL", "postgresql": "VARCHAR(64) NOT NULL"}},
			{name: "name", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "TEXT NOT NULL", "postgresql": "TEXT NOT NULL"}},
			{name: "save_path", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "size", definition: map[string]string{"sqlite": "INTEGER", "mysql": "BIGINT", "postgresql": "BIGINT"}},
			{name: "progress", definition: map[string]string{"sqlite": "REAL", "mysql": "DOUBLE", "postgresql": "DOUBLE PRECISION"}},
			{name: "state", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(50)", "postgresql": "VARCHAR(50)"}},
			{name: "sites", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "group", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "official_site", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "details", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "downloader_id", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(64) NOT NULL", "postgresql": "VARCHAR(64) NOT NULL"}},
			{name: "last_seen", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
			{name: "iyuu_last_check", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
			{name: "seeders", definition: map[string]string{"sqlite": "INTEGER DEFAULT 0", "mysql": "INT DEFAULT 0", "postgresql": "INTEGER DEFAULT 0"}},
			{name: "is_hidden", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "TINYINT(1) NOT NULL DEFAULT 0", "postgresql": "INTEGER NOT NULL DEFAULT 0"}},
			{name: "hidden_reason", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "hidden_at", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
		},
		"torrent_upload_stats": {
			{name: "hash", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(64) NOT NULL", "postgresql": "VARCHAR(64) NOT NULL"}},
			{name: "downloader_id", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(64) NOT NULL", "postgresql": "VARCHAR(64) NOT NULL"}},
			{name: "uploaded", definition: map[string]string{"sqlite": "INTEGER DEFAULT 0", "mysql": "BIGINT DEFAULT 0", "postgresql": "BIGINT DEFAULT 0"}},
			{name: "is_hidden", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "TINYINT(1) NOT NULL DEFAULT 0", "postgresql": "INTEGER NOT NULL DEFAULT 0"}},
			{name: "hidden_reason", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "hidden_at", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
		},
		"sites": {
			{name: "site", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "nickname", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "base_url", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "special_tracker_domain", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "group", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "description", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "cookie", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "passkey", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "migration", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 1", "mysql": "INT NOT NULL DEFAULT 1", "postgresql": "INTEGER NOT NULL DEFAULT 1"}},
			{name: "speed_limit", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "INT NOT NULL DEFAULT 0", "postgresql": "INTEGER NOT NULL DEFAULT 0"}},
			{name: "ratio_threshold", definition: map[string]string{"sqlite": "REAL NOT NULL DEFAULT 3.0", "mysql": "DOUBLE NOT NULL DEFAULT 3.0", "postgresql": "DOUBLE PRECISION NOT NULL DEFAULT 3.0"}},
			{name: "seed_speed_limit", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 5", "mysql": "INT NOT NULL DEFAULT 5", "postgresql": "INTEGER NOT NULL DEFAULT 5"}},
			{name: "can_publish", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 1", "mysql": "TINYINT(1) NOT NULL DEFAULT 1", "postgresql": "INTEGER NOT NULL DEFAULT 1"}},
			{name: "forbidden_transfer_sites", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "sort_order", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "INT NOT NULL DEFAULT 0", "postgresql": "INTEGER NOT NULL DEFAULT 0"}},
		},
		"app_settings": {
			{name: "setting_key", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(64) NOT NULL", "postgresql": "VARCHAR(64) NOT NULL"}},
			{name: "value_json", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "LONGTEXT NOT NULL", "postgresql": "TEXT NOT NULL"}},
			{name: "created_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
			{name: "updated_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
		},
		"seed_parameters": {
			{name: "hash", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(64) NOT NULL", "postgresql": "VARCHAR(64) NOT NULL"}},
			{name: "torrent_id", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(255) NOT NULL", "postgresql": "VARCHAR(255) NOT NULL"}},
			{name: "site_name", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(255) NOT NULL", "postgresql": "VARCHAR(255) NOT NULL"}},
			{name: "nickname", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "name", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "title", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "subtitle", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "imdb_link", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "douban_link", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "tmdb_link", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "type", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(100)", "postgresql": "VARCHAR(100)"}},
			{name: "medium", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(100)", "postgresql": "VARCHAR(100)"}},
			{name: "video_codec", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(100)", "postgresql": "VARCHAR(100)"}},
			{name: "audio_codec", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(100)", "postgresql": "VARCHAR(100)"}},
			{name: "resolution", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(100)", "postgresql": "VARCHAR(100)"}},
			{name: "team", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(100)", "postgresql": "VARCHAR(100)"}},
			{name: "official_site", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "source", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(100)", "postgresql": "VARCHAR(100)"}},
			{name: "tags", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "poster", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "screenshots", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "screenshot_review_status", definition: map[string]string{"sqlite": "TEXT NOT NULL DEFAULT 'none'", "mysql": "VARCHAR(20) NOT NULL DEFAULT 'none'", "postgresql": "VARCHAR(20) NOT NULL DEFAULT 'none'"}},
			{name: "statement", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "body", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "mediainfo", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "title_components", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "removed_ardtudeclarations", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "is_reviewed", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "TINYINT(1) NOT NULL DEFAULT 0", "postgresql": "BOOLEAN NOT NULL DEFAULT FALSE"}},
			{name: "mediainfo_status", definition: map[string]string{"sqlite": "TEXT DEFAULT 'pending'", "mysql": "VARCHAR(20) DEFAULT 'pending'", "postgresql": "VARCHAR(20) DEFAULT 'pending'"}},
			{name: "bdinfo_task_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(36)", "postgresql": "VARCHAR(36)"}},
			{name: "bdinfo_started_at", definition: map[string]string{"sqlite": "TEXT", "mysql": "DATETIME", "postgresql": "TIMESTAMP"}},
			{name: "bdinfo_completed_at", definition: map[string]string{"sqlite": "TEXT", "mysql": "DATETIME", "postgresql": "TIMESTAMP"}},
			{name: "bdinfo_error", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "publish_at", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
			{name: "last_publish_at", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
			{name: "created_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
			{name: "updated_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
		},
		"publish_queue_tasks": {
			{name: "group_id", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(64) NOT NULL", "postgresql": "VARCHAR(64) NOT NULL"}},
			{name: "status", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(32) NOT NULL", "postgresql": "VARCHAR(32) NOT NULL"}},
			{name: "task_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "publish_trigger", definition: map[string]string{"sqlite": "TEXT NOT NULL DEFAULT 'queue'", "mysql": "VARCHAR(32) NOT NULL DEFAULT 'queue'", "postgresql": "VARCHAR(32) NOT NULL DEFAULT 'queue'"}},
			{name: "scene", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(32)", "postgresql": "VARCHAR(32)"}},
			{name: "source_site", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "torrent_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "target_site", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "downloader_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "title", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "subtitle", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "payload_json", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "LONGTEXT NOT NULL", "postgresql": "TEXT NOT NULL"}},
			{name: "upload_data_json", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "LONGTEXT NOT NULL", "postgresql": "TEXT NOT NULL"}},
			{name: "context_json", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "LONGTEXT NOT NULL", "postgresql": "TEXT NOT NULL"}},
			{name: "attempt_count", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "INT NOT NULL DEFAULT 0", "postgresql": "INTEGER NOT NULL DEFAULT 0"}},
			{name: "scheduled_at", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
			{name: "next_run_at", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
			{name: "started_at", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
			{name: "finished_at", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
			{name: "last_error", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "last_result", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "created_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
			{name: "updated_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
		},
		"scheduled_seed_tasks": {
			{name: "name", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(128) NOT NULL", "postgresql": "VARCHAR(128) NOT NULL"}},
			{name: "status", definition: map[string]string{"sqlite": "TEXT NOT NULL DEFAULT 'active'", "mysql": "VARCHAR(16) NOT NULL DEFAULT 'active'", "postgresql": "VARCHAR(16) NOT NULL DEFAULT 'active'"}},
			{name: "seeds_json", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "LONGTEXT NOT NULL", "postgresql": "TEXT NOT NULL"}},
			{name: "target_sites_json", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "LONGTEXT NOT NULL", "postgresql": "TEXT NOT NULL"}},
			{name: "interval_minutes", definition: map[string]string{"sqlite": "INTEGER NOT NULL", "mysql": "INT NOT NULL", "postgresql": "INTEGER NOT NULL"}},
			{name: "current_seed_index", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "INT NOT NULL DEFAULT 0", "postgresql": "INTEGER NOT NULL DEFAULT 0"}},
			{name: "current_site_index", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "INT NOT NULL DEFAULT 0", "postgresql": "INTEGER NOT NULL DEFAULT 0"}},
			{name: "total_published", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "INT NOT NULL DEFAULT 0", "postgresql": "INTEGER NOT NULL DEFAULT 0"}},
			{name: "total_skipped", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "INT NOT NULL DEFAULT 0", "postgresql": "INTEGER NOT NULL DEFAULT 0"}},
			{name: "loop_enabled", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "TINYINT(1) NOT NULL DEFAULT 0", "postgresql": "BOOLEAN NOT NULL DEFAULT FALSE"}},
			{name: "trigger_tag", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(64) NOT NULL", "postgresql": "VARCHAR(64) NOT NULL"}},
			{name: "last_run_at", definition: map[string]string{"sqlite": "TEXT NULL", "mysql": "DATETIME NULL", "postgresql": "TIMESTAMP NULL"}},
			{name: "next_run_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
			{name: "created_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
			{name: "updated_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
		},
		"resource_info": {
			{name: "title", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "year", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(16)", "postgresql": "VARCHAR(16)"}},
			{name: "country", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "douban_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "imdb_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "tmdb_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "poster_url", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "summary", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "screenshots", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "created_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
			{name: "updated_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
		},
		"publish_logs": {
			{name: "publish_trigger", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(32) NOT NULL", "postgresql": "VARCHAR(32) NOT NULL"}},
			{name: "scene", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(32)", "postgresql": "VARCHAR(32)"}},
			{name: "queue_task_id", definition: map[string]string{"sqlite": "INTEGER NULL", "mysql": "BIGINT NULL", "postgresql": "BIGINT NULL"}},
			{name: "queue_group_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "task_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "torrent_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "source_site", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "target_site", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(255)", "postgresql": "VARCHAR(255)"}},
			{name: "downloader_id", definition: map[string]string{"sqlite": "TEXT", "mysql": "VARCHAR(64)", "postgresql": "VARCHAR(64)"}},
			{name: "title", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "subtitle", definition: map[string]string{"sqlite": "TEXT", "mysql": "TEXT", "postgresql": "TEXT"}},
			{name: "status", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "VARCHAR(32) NOT NULL", "postgresql": "VARCHAR(32) NOT NULL"}},
			{name: "result_url", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "logs", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "auto_add_result", definition: map[string]string{"sqlite": "TEXT", "mysql": "LONGTEXT", "postgresql": "TEXT"}},
			{name: "cost_ms", definition: map[string]string{"sqlite": "INTEGER NOT NULL DEFAULT 0", "mysql": "BIGINT NOT NULL DEFAULT 0", "postgresql": "BIGINT NOT NULL DEFAULT 0"}},
			{name: "created_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
			{name: "updated_at", definition: map[string]string{"sqlite": "TEXT NOT NULL", "mysql": "DATETIME NOT NULL", "postgresql": "TIMESTAMP NOT NULL"}},
		},
	}
}

func (m *SchemaManager) indexSpecs() []schemaIndexSpec {
	return []schemaIndexSpec{
		{table: "publish_queue_tasks", name: "idx_publish_queue_status_next", columns: []string{"status", "next_run_at"}},
		{table: "publish_queue_tasks", name: "idx_publish_queue_group_id", columns: []string{"group_id"}},
		{table: "publish_queue_tasks", name: "idx_publish_queue_created_at", columns: []string{"created_at"}},
		{table: "publish_queue_tasks", name: "idx_publish_queue_torrent_id", columns: []string{"torrent_id"}},
		{table: "publish_queue_tasks", name: "idx_publish_queue_target_site", columns: []string{"target_site"}},
		{table: "publish_queue_tasks", name: "idx_publish_queue_downloader_id", columns: []string{"downloader_id"}},

		{table: "publish_logs", name: "idx_publish_logs_created_at", columns: []string{"created_at"}},
		{table: "publish_logs", name: "idx_publish_logs_status", columns: []string{"status"}},
		{table: "publish_logs", name: "idx_publish_logs_target_site", columns: []string{"target_site"}},
		{table: "publish_logs", name: "idx_publish_logs_torrent_id", columns: []string{"torrent_id"}},
		{table: "publish_logs", name: "idx_publish_logs_publish_trigger", columns: []string{"publish_trigger"}},
		{table: "publish_logs", name: "idx_publish_logs_scene", columns: []string{"scene"}},
		{table: "publish_logs", name: "idx_publish_logs_queue_task_id", columns: []string{"queue_task_id"}},
		{table: "publish_logs", name: "idx_publish_logs_queue_group_id", columns: []string{"queue_group_id"}},

		{table: "scheduled_seed_tasks", name: "idx_sched_seed_status_next_run", columns: []string{"status", "next_run_at"}},
		{table: "scheduled_seed_tasks", name: "idx_sched_seed_trigger_tag", columns: []string{"trigger_tag"}},

		{table: "auto_seed_rules", name: "idx_auto_seed_rules_enabled_next", columns: []string{"enabled", "next_run_at"}},
		{table: "auto_seed_items", name: "idx_auto_seed_items_rule_guid", columns: []string{"rule_id", "guid"}},
		{table: "auto_seed_items", name: "idx_auto_seed_items_status", columns: []string{"status"}},
		{table: "auto_seed_items", name: "idx_auto_seed_items_downloader", columns: []string{"downloader_id"}},
		{table: "auto_seed_items", name: "idx_auto_seed_items_torrent_id", columns: []string{"torrent_id"}},

		{table: "resource_info", name: "idx_resource_info_douban_id", columns: []string{"douban_id"}},
		{table: "resource_info", name: "idx_resource_info_imdb_id", columns: []string{"imdb_id"}},
		{table: "resource_info", name: "idx_resource_info_tmdb_id", columns: []string{"tmdb_id"}},
		{table: "resource_info", name: "idx_resource_info_updated_at", columns: []string{"updated_at"}},
	}
}

func (m *SchemaManager) ensureTableColumns(tableName string, specs []schemaColumnSpec) error {
	columnSet, err := m.listColumnSet(tableName)
	if err != nil {
		return fmt.Errorf("读取表字段失败 table=%s err=%w", tableName, err)
	}

	for _, spec := range specs {
		if _, exists := columnSet[strings.ToLower(spec.name)]; exists {
			continue
		}
		definition, ok := spec.definition[m.store.DBType]
		if !ok || strings.TrimSpace(definition) == "" {
			definition = spec.definition["sqlite"]
		}
		if strings.TrimSpace(definition) == "" {
			return fmt.Errorf("字段定义缺失 table=%s column=%s db=%s", tableName, spec.name, m.store.DBType)
		}

		sqlText := fmt.Sprintf(
			"ALTER TABLE %s ADD COLUMN %s %s",
			quoteIdentifierByDB(m.store.DBType, tableName),
			quoteIdentifierByDB(m.store.DBType, spec.name),
			definition,
		)
		if err := m.store.DB.Exec(sqlText).Error; err != nil {
			return fmt.Errorf("补齐字段失败 table=%s column=%s err=%w", tableName, spec.name, err)
		}
		logx.Infof(schemaLogModule, "补齐缺失字段 table=%s column=%s", tableName, spec.name)
	}
	return nil
}

func (m *SchemaManager) listColumnSet(tableName string) (map[string]struct{}, error) {
	result := map[string]struct{}{}

	switch m.store.DBType {
	case "mysql":
		// NOTE: MySQL driver returns metadata column names as "COLUMN_NAME" (upper-case).
		// Use an explicit alias + named struct so GORM scans into the field instead of
		// attempting to scan into the struct itself.
		type columnNameRow struct {
			ColumnName string `gorm:"column:column_name"`
		}
		rows := make([]columnNameRow, 0)
		if err := m.store.DB.Raw(
			`SELECT COLUMN_NAME AS column_name
			 FROM information_schema.columns
			 WHERE table_schema = DATABASE()
			   AND table_name = ?`,
			tableName,
		).Scan(&rows).Error; err != nil {
			return nil, err
		}
		for _, row := range rows {
			result[strings.ToLower(strings.TrimSpace(row.ColumnName))] = struct{}{}
		}
	case "postgresql":
		type columnNameRow struct {
			ColumnName string `gorm:"column:column_name"`
		}
		rows := make([]columnNameRow, 0)
		if err := m.store.DB.Raw(
			`SELECT column_name
			 FROM information_schema.columns
			 WHERE table_schema = CURRENT_SCHEMA()
			   AND table_name = ?`,
			tableName,
		).Scan(&rows).Error; err != nil {
			return nil, err
		}
		for _, row := range rows {
			result[strings.ToLower(strings.TrimSpace(row.ColumnName))] = struct{}{}
		}
	default:
		if !isSafeIdentifier(tableName) {
			return nil, fmt.Errorf("非法表名: %s", tableName)
		}
		rows := make([]struct {
			Name string `gorm:"column:name"`
		}, 0)
		pragmaSQL := fmt.Sprintf("PRAGMA table_info(%s)", quoteIdentifierByDB("sqlite", tableName))
		if err := m.store.DB.Raw(pragmaSQL).Scan(&rows).Error; err != nil {
			return nil, err
		}
		for _, row := range rows {
			result[strings.ToLower(strings.TrimSpace(row.Name))] = struct{}{}
		}
	}
	return result, nil
}

func (m *SchemaManager) ensureIndex(spec schemaIndexSpec) error {
	if len(spec.columns) == 0 {
		return nil
	}

	columnList := make([]string, 0, len(spec.columns))
	for _, column := range spec.columns {
		columnList = append(columnList, quoteIdentifierByDB(m.store.DBType, column))
	}

	switch m.store.DBType {
	case "mysql":
		exists, err := m.mysqlIndexExists(spec.table, spec.name)
		if err != nil {
			return fmt.Errorf("检查索引失败 table=%s index=%s err=%w", spec.table, spec.name, err)
		}
		if exists {
			return nil
		}
		sqlText := fmt.Sprintf(
			"CREATE INDEX %s ON %s(%s)",
			quoteIdentifierByDB(m.store.DBType, spec.name),
			quoteIdentifierByDB(m.store.DBType, spec.table),
			strings.Join(columnList, ", "),
		)
		if err := m.store.DB.Exec(sqlText).Error; err != nil {
			return fmt.Errorf("创建索引失败 table=%s index=%s err=%w", spec.table, spec.name, err)
		}
	default:
		sqlText := fmt.Sprintf(
			"CREATE INDEX IF NOT EXISTS %s ON %s(%s)",
			quoteIdentifierByDB(m.store.DBType, spec.name),
			quoteIdentifierByDB(m.store.DBType, spec.table),
			strings.Join(columnList, ", "),
		)
		if err := m.store.DB.Exec(sqlText).Error; err != nil {
			return fmt.Errorf("创建索引失败 table=%s index=%s err=%w", spec.table, spec.name, err)
		}
	}
	return nil
}

// createAutoSeedMySQLTables 使用明确字段类型创建 MySQL 自动发种表。
// 参数/返回：无入参；成功返回 nil，DDL 失败时返回具体错误。
// 失败场景：数据库连接异常或 CREATE TABLE 失败。
// 副作用：会创建 auto_seed_rules 与 auto_seed_items 表。
func (m *SchemaManager) createAutoSeedMySQLTables() error {
	sqls := []string{
		`CREATE TABLE IF NOT EXISTS auto_seed_rules (
			id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
			name VARCHAR(255),
			enabled TINYINT(1) NOT NULL DEFAULT 1,
			paused_reason VARCHAR(255),
			source_site VARCHAR(255),
			rss_url LONGTEXT,
			downloader_id VARCHAR(64),
			save_path VARCHAR(1024),
			download_url LONGTEXT,
			auto_pause TINYINT(1) NOT NULL DEFAULT 0,
			auto_organize TINYINT(1) NOT NULL DEFAULT 1,
			min_size_gb DOUBLE DEFAULT 0,
			max_size_gb DOUBLE DEFAULT 0,
			types_json LONGTEXT,
			media_json LONGTEXT,
			tags_json LONGTEXT,
			target_sites_json LONGTEXT,
			pull_interval_minutes INT NOT NULL DEFAULT 30,
			publish_interval_minutes INT NOT NULL DEFAULT 0,
			publish_concurrency INT NOT NULL DEFAULT 1,
			seed_retention_minutes INT NOT NULL DEFAULT 0,
			last_run_at DATETIME NULL,
			next_run_at DATETIME NOT NULL,
			created_at DATETIME NOT NULL,
			updated_at DATETIME NOT NULL
		) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
		`CREATE TABLE IF NOT EXISTS auto_seed_items (
			id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
			rule_id BIGINT NOT NULL DEFAULT 0,
			source_site VARCHAR(255),
			guid VARCHAR(255),
			torrent_url LONGTEXT,
			detail_url LONGTEXT,
			name LONGTEXT,
			subtitle TEXT,
			size_bytes BIGINT NOT NULL DEFAULT 0,
			resource_type VARCHAR(32),
			medium VARCHAR(64),
			tags_json LONGTEXT,
			status VARCHAR(32),
			reject_reason VARCHAR(255),
			publish_results_json LONGTEXT,
			downloader_id VARCHAR(64),
			downloader_hash VARCHAR(64),
			progress DOUBLE NOT NULL DEFAULT 0,
			downloaded TINYINT(1) NOT NULL DEFAULT 0,
			torrent_id VARCHAR(255),
			site_name VARCHAR(255),
			pushed_at DATETIME NULL,
			organized_at DATETIME NULL,
			published_at DATETIME NULL,
			created_at DATETIME NOT NULL,
			updated_at DATETIME NOT NULL
		) ENGINE=InnoDB ROW_FORMAT=Dynamic`,
	}
	for _, sqlText := range sqls {
		if err := m.store.DB.Exec(sqlText).Error; err != nil {
			return fmt.Errorf("创建自动发种表失败: %w", err)
		}
	}
	return nil
}

// fixAutoSeedMySQLColumnTypes 修正 GORM 自动迁移在 MySQL 下生成的自动发种字段类型。
// 参数/返回：无入参；成功返回 nil，DDL 失败时返回具体错误。
// 失败场景：数据库连接异常、ALTER TABLE 执行失败。
// 副作用：会把自动发种表中需索引或排序的 TEXT/LONGTEXT 字段调整为 VARCHAR/DATETIME。
func (m *SchemaManager) fixAutoSeedMySQLColumnTypes() error {
	if m.store.DBType != "mysql" {
		return nil
	}

	sqls := []string{
		"UPDATE `auto_seed_rules` SET `last_run_at` = NULL WHERE CAST(`last_run_at` AS CHAR) = ''",
		"UPDATE `auto_seed_rules` SET `next_run_at` = NOW() WHERE `next_run_at` IS NULL OR CAST(`next_run_at` AS CHAR) = ''",
		"UPDATE `auto_seed_rules` SET `created_at` = NOW() WHERE `created_at` IS NULL OR CAST(`created_at` AS CHAR) = ''",
		"UPDATE `auto_seed_rules` SET `updated_at` = NOW() WHERE `updated_at` IS NULL OR CAST(`updated_at` AS CHAR) = ''",
		"UPDATE `auto_seed_items` SET `pushed_at` = NULL WHERE CAST(`pushed_at` AS CHAR) = ''",
		"UPDATE `auto_seed_items` SET `organized_at` = NULL WHERE CAST(`organized_at` AS CHAR) = ''",
		"UPDATE `auto_seed_items` SET `published_at` = NULL WHERE CAST(`published_at` AS CHAR) = ''",
		"UPDATE `auto_seed_items` SET `created_at` = NOW() WHERE `created_at` IS NULL OR CAST(`created_at` AS CHAR) = ''",
		"UPDATE `auto_seed_items` SET `updated_at` = NOW() WHERE `updated_at` IS NULL OR CAST(`updated_at` AS CHAR) = ''",
		"ALTER TABLE `auto_seed_rules` MODIFY COLUMN `name` VARCHAR(255)",
		"ALTER TABLE `auto_seed_rules` MODIFY COLUMN `paused_reason` VARCHAR(255)",
		"ALTER TABLE `auto_seed_rules` MODIFY COLUMN `source_site` VARCHAR(255)",
		"ALTER TABLE `auto_seed_rules` MODIFY COLUMN `downloader_id` VARCHAR(64)",
		"ALTER TABLE `auto_seed_rules` MODIFY COLUMN `save_path` VARCHAR(1024)",
		"ALTER TABLE `auto_seed_rules` MODIFY COLUMN `seed_retention_minutes` INT NOT NULL DEFAULT 0",
		"ALTER TABLE `auto_seed_rules` MODIFY COLUMN `last_run_at` DATETIME NULL",
		"ALTER TABLE `auto_seed_rules` MODIFY COLUMN `next_run_at` DATETIME NOT NULL",
		"ALTER TABLE `auto_seed_rules` MODIFY COLUMN `created_at` DATETIME NOT NULL",
		"ALTER TABLE `auto_seed_rules` MODIFY COLUMN `updated_at` DATETIME NOT NULL",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `source_site` VARCHAR(255)",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `guid` VARCHAR(255)",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `resource_type` VARCHAR(32)",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `medium` VARCHAR(64)",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `subtitle` TEXT",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `status` VARCHAR(32)",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `reject_reason` VARCHAR(255)",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `downloader_id` VARCHAR(64)",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `downloader_hash` VARCHAR(64)",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `torrent_id` VARCHAR(255)",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `site_name` VARCHAR(255)",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `pushed_at` DATETIME NULL",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `organized_at` DATETIME NULL",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `published_at` DATETIME NULL",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `created_at` DATETIME NOT NULL",
		"ALTER TABLE `auto_seed_items` MODIFY COLUMN `updated_at` DATETIME NOT NULL",
	}

	for _, sqlText := range sqls {
		if err := m.store.DB.Exec(sqlText).Error; err != nil {
			return fmt.Errorf("修正自动发种字段类型失败 sql=%s err=%w", sqlText, err)
		}
	}
	return nil
}

func (m *SchemaManager) mysqlIndexExists(tableName, indexName string) (bool, error) {
	rows := make([]struct {
		Count int64 `gorm:"column:cnt"`
	}, 0)
	if err := m.store.DB.Raw(
		`SELECT COUNT(1) AS cnt
		 FROM information_schema.statistics
		 WHERE table_schema = DATABASE()
		   AND table_name = ?
		   AND index_name = ?`,
		tableName,
		indexName,
	).Scan(&rows).Error; err != nil {
		return false, err
	}
	if len(rows) == 0 {
		return false, nil
	}
	return rows[0].Count > 0, nil
}

func quoteIdentifierByDB(dbType string, name string) string {
	switch dbType {
	case "postgresql":
		return `"` + strings.ReplaceAll(name, `"`, `""`) + `"`
	default:
		return "`" + strings.ReplaceAll(name, "`", "``") + "`"
	}
}

func isSafeIdentifier(identifier string) bool {
	trimmed := strings.TrimSpace(identifier)
	if trimmed == "" {
		return false
	}
	for _, ch := range trimmed {
		if (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '_' {
			continue
		}
		return false
	}
	return true
}

// fixSeedParametersColumnTypes 修复 seed_parameters 表中某些列的类型。
// 旧版本 removed_ardtudeclarations 列可能是 VARCHAR(255)，导致长 JSON 数据写入失败。
// 参数/返回：无参数，成功返回 nil，失败返回详细错误。
// 失败场景：数据库连接异常、DDL 执行失败。
// 副作用：会执行 ALTER TABLE MODIFY COLUMN。
func (m *SchemaManager) fixSeedParametersColumnTypes() error {
	if m.store.DBType != "mysql" {
		// PostgreSQL 和 SQLite 的 TEXT 类型无长度限制，无需修复
		return nil
	}

	// 检查 removed_ardtudeclarations 列的类型
	type columnTypeRow struct {
		DataType   string `gorm:"column:data_type"`
		ColumnType string `gorm:"column:column_type"`
	}
	rows := make([]columnTypeRow, 0)
	if err := m.store.DB.Raw(
		`SELECT DATA_TYPE AS data_type, COLUMN_TYPE AS column_type
		 FROM information_schema.columns
		 WHERE table_schema = DATABASE()
		   AND table_name = 'seed_parameters'
		   AND column_name = 'removed_ardtudeclarations'`,
	).Scan(&rows).Error; err != nil {
		return fmt.Errorf("检查 seed_parameters.removed_ardtudeclarations 列类型失败: %w", err)
	}

	if len(rows) == 0 {
		// 列不存在，由 ensureTableColumns 处理
		return nil
	}

	// 如果是 varchar 类型，需要修改为 text
	if rows[0].DataType == "varchar" {
		logx.Infof(schemaLogModule, "检测到 removed_ardtudeclarations 列为 VARCHAR，正在修改为 TEXT")
		sqlText := "ALTER TABLE `seed_parameters` MODIFY COLUMN `removed_ardtudeclarations` TEXT"
		if err := m.store.DB.Exec(sqlText).Error; err != nil {
			return fmt.Errorf("修改 removed_ardtudeclarations 列类型失败: %w", err)
		}
		logx.Infof(schemaLogModule, "✓ 成功修改 removed_ardtudeclarations 列类型为 TEXT")
	}

	return nil
}
