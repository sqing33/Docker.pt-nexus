package repository

import (
	"errors"
	"fmt"
	"strings"

	"gorm.io/gorm"
)

type MigrateRepository struct {
	store *Store
}

func NewMigrateRepository(store *Store) *MigrateRepository {
	return &MigrateRepository{store: store}
}

func (r *MigrateRepository) DB() *gorm.DB {
	return r.store.DB
}

// ReplaceUnseededPlaceholderHash 将 torrents 表中指定站点的“未做种”占位记录 hash 替换为真实 infohash。
// 参数/返回：按 name+size+downloader_id+sites 定位；返回旧 hash 与是否完成替换。
// 失败场景：查询失败、主键冲突或更新失败时返回 error。
// 副作用：写入 torrents（UPDATE），并同步更新 torrent_upload_stats（若存在）。
func (r *MigrateRepository) ReplaceUnseededPlaceholderHash(name string, size int64, downloaderID string, siteNickname string, newHash string) (string, bool, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return "", false, errors.New("repo is nil")
	}
	name = strings.TrimSpace(name)
	downloaderID = strings.TrimSpace(downloaderID)
	siteNickname = strings.TrimSpace(siteNickname)
	newHash = strings.TrimSpace(newHash)
	if name == "" || size <= 0 || downloaderID == "" || siteNickname == "" || newHash == "" {
		return "", false, nil
	}

	row := struct {
		Hash string `gorm:"column:hash"`
	}{}
	if err := r.store.DB.Raw(
		`SELECT hash
		 FROM torrents
		 WHERE name = ? AND size = ? AND downloader_id = ? AND sites = ? AND state = '未做种'
		   AND (is_hidden = 0 OR is_hidden IS NULL)
		 ORDER BY last_seen DESC
		 LIMIT 1`,
		name, size, downloaderID, siteNickname,
	).Scan(&row).Error; err != nil {
		return "", false, err
	}

	oldHash := strings.TrimSpace(row.Hash)
	if oldHash == "" {
		return "", false, nil
	}
	if oldHash == newHash {
		return oldHash, false, nil
	}

	updated := false
	txErr := r.store.DB.Transaction(func(tx *gorm.DB) error {
		conflict := struct {
			Count int64 `gorm:"column:cnt"`
		}{}
		if err := tx.Raw(
			`SELECT COUNT(1) AS cnt
			 FROM torrents
			 WHERE hash = ? AND downloader_id = ?
			   AND (is_hidden = 0 OR is_hidden IS NULL)`,
			newHash, downloaderID,
		).Scan(&conflict).Error; err != nil {
			return err
		}
		if conflict.Count > 0 {
			return fmt.Errorf("目标 hash 已存在，无法替换 old_hash=%s new_hash=%s downloader_id=%s", oldHash, newHash, downloaderID)
		}

		result := tx.Exec(
			`UPDATE torrents
			 SET hash = ?
			 WHERE hash = ? AND downloader_id = ? AND name = ? AND size = ? AND sites = ? AND state = '未做种'
			   AND (is_hidden = 0 OR is_hidden IS NULL)`,
			newHash, oldHash, downloaderID, name, size, siteNickname,
		)
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return nil
		}
		updated = true

		if err := tx.Exec(
			`UPDATE torrent_upload_stats
			 SET hash = ?
			 WHERE hash = ? AND downloader_id = ?
			   AND (is_hidden = 0 OR is_hidden IS NULL)`,
			newHash, oldHash, downloaderID,
		).Error; err != nil {
			return err
		}
		return nil
	})
	if txErr != nil {
		return oldHash, false, txErr
	}
	return oldHash, updated, nil
}

type siteGroupDescriptionRow struct {
	Description *string `gorm:"column:description"`
	GroupValue  *string `gorm:"column:group_value"`
}

// ListSitesGroupAndDescription 列出 sites 表中用于“官组致谢声明”匹配的字段。
// 参数/返回：无入参；返回每条站点的 group 与 description（允许为空）。
// 失败场景：数据库查询失败时返回 error。
// 副作用：无副作用，仅读取 sites 表。
func (r *MigrateRepository) ListSitesGroupAndDescription() ([]map[string]any, error) {
	rows := make([]siteGroupDescriptionRow, 0)
	groupColumn := r.store.GroupColumn()
	query := "SELECT description, " + groupColumn + " AS group_value FROM sites"
	if err := r.store.DB.Raw(query).Scan(&rows).Error; err != nil {
		return nil, err
	}
	out := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		desc := ""
		group := ""
		if row.Description != nil {
			desc = strings.TrimSpace(*row.Description)
		}
		if row.GroupValue != nil {
			group = strings.TrimSpace(*row.GroupValue)
		}
		out = append(out, map[string]any{
			"description": desc,
			"group":       group,
		})
	}
	return out, nil
}

type siteNicknameGroupRow struct {
	Nickname   string  `gorm:"column:nickname"`
	GroupValue *string `gorm:"column:group_value"`
}

// FindSiteNicknameByGroup 根据制作组名称匹配 sites.group，并返回命中的站点 nickname。
// 参数/返回：releaseGroup 为制作组名（支持包含 '@' 或前导 '-'）；命中返回 nickname，未命中返回空字符串。
// 失败场景：数据库查询失败时返回 error。
// 副作用：无副作用，仅读取 sites 表。
func (r *MigrateRepository) FindSiteNicknameByGroup(releaseGroup string) (string, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return "", errors.New("repo is nil")
	}

	normalized := normalizeReleaseGroup(releaseGroup)
	if normalized == "" {
		return "", nil
	}

	rows := make([]siteNicknameGroupRow, 0)
	groupColumn := r.store.GroupColumn()
	query := "SELECT nickname, " + groupColumn + " AS group_value FROM sites"
	if err := r.store.DB.Raw(query).Scan(&rows).Error; err != nil {
		return "", err
	}

	for _, row := range rows {
		if row.GroupValue == nil || strings.TrimSpace(*row.GroupValue) == "" {
			continue
		}
		if groupMatches(*row.GroupValue, normalized) {
			return strings.TrimSpace(row.Nickname), nil
		}
	}

	return "", nil
}

func normalizeReleaseGroup(value string) string {
	v := strings.TrimSpace(value)
	if v == "" {
		return ""
	}
	if strings.HasPrefix(strings.ToLower(v), "team.") {
		v = strings.TrimSpace(v[len("team."):])
	}
	if strings.Contains(v, "@") {
		parts := strings.Split(v, "@")
		if len(parts) >= 2 && strings.TrimSpace(parts[1]) != "" {
			v = strings.TrimSpace(parts[1])
		}
	}
	return strings.TrimSpace(strings.TrimLeft(v, "-"))
}

func groupMatches(siteGroup string, releaseGroup string) bool {
	sg := strings.TrimSpace(siteGroup)
	rg := strings.TrimSpace(releaseGroup)
	if sg == "" || rg == "" {
		return false
	}

	parts := strings.FieldsFunc(sg, func(r rune) bool {
		switch r {
		case '/', '\\', '|', ',', ' ', '\t', '\n', '\r':
			return true
		default:
			return false
		}
	})
	for _, part := range parts {
		cleaned := strings.TrimSpace(strings.TrimLeft(part, "-"))
		if cleaned == "" {
			continue
		}
		if strings.EqualFold(cleaned, rg) {
			return true
		}
	}
	return false
}

func (r *MigrateRepository) GetSiteByName(name string) (map[string]any, error) {
	row := map[string]any{}
	err := r.store.DB.Table("sites").Where("nickname = ? OR site = ?", name, name).Limit(1).Scan(&row).Error
	if err != nil {
		return nil, err
	}
	if len(row) == 0 {
		return nil, gorm.ErrRecordNotFound
	}
	return row, nil
}

func (r *MigrateRepository) GetSeedParameter(torrentID, siteName string) (map[string]any, error) {
	row := map[string]any{}
	err := r.store.DB.Table("seed_parameters").Where("torrent_id = ? AND (site_name = ? OR nickname = ?)", torrentID, siteName, siteName).Order("updated_at DESC").Limit(1).Scan(&row).Error
	if err != nil {
		return nil, err
	}
	if len(row) == 0 {
		lowered := strings.ToLower(strings.TrimSpace(siteName))
		if lowered != "" {
			err = r.store.DB.Table("seed_parameters").Where("torrent_id = ? AND (LOWER(site_name) = ? OR LOWER(nickname) = ?)", torrentID, lowered, lowered).Order("updated_at DESC").Limit(1).Scan(&row).Error
			if err != nil {
				return nil, err
			}
		}
	}
	if len(row) == 0 {
		return nil, gorm.ErrRecordNotFound
	}
	return row, nil
}

func (r *MigrateRepository) GetSeedParameterByKey(hash, torrentID, siteName string) (map[string]any, error) {
	row := map[string]any{}
	err := r.store.DB.Table("seed_parameters").Where("hash = ? AND torrent_id = ? AND site_name = ?", hash, torrentID, siteName).Limit(1).Scan(&row).Error
	if err != nil {
		return nil, err
	}
	if len(row) == 0 {
		return nil, gorm.ErrRecordNotFound
	}
	return row, nil
}

func (r *MigrateRepository) GetSeedParametersByName(name string) ([]map[string]any, error) {
	rows := make([]map[string]any, 0)
	err := r.store.DB.Table("seed_parameters").
		Where("name = ?", name).
		Order("updated_at DESC").
		Scan(&rows).Error
	if err != nil {
		return nil, err
	}
	return rows, nil
}

func (r *MigrateRepository) GetCurrentTorrentByName(name string) (map[string]any, error) {
	row := map[string]any{}
	err := r.store.DB.Raw(`
		SELECT t.hash, t.name, t.save_path, t.downloader_id, t.sites, t.details, t.size
		FROM torrents t
		JOIN (
			SELECT name, MAX(last_seen) AS max_last_seen
			FROM torrents
			WHERE name = ? AND (is_hidden = 0 OR is_hidden IS NULL)
			GROUP BY name
		) latest ON latest.name = t.name AND latest.max_last_seen = t.last_seen
		WHERE (t.is_hidden = 0 OR t.is_hidden IS NULL)
		LIMIT 1
	`, name).Scan(&row).Error
	if err != nil {
		return nil, err
	}
	if len(row) == 0 {
		return nil, gorm.ErrRecordNotFound
	}
	return row, nil
}

func (r *MigrateRepository) GetCurrentTorrentByHash(hash string) (map[string]any, error) {
	row := map[string]any{}
	err := r.store.DB.Raw(`
		SELECT t.hash, t.name, t.save_path, t.downloader_id, t.sites, t.details, t.size
		FROM torrents t
		JOIN (
			SELECT hash, MAX(last_seen) AS max_last_seen
			FROM torrents
			WHERE hash = ? AND (is_hidden = 0 OR is_hidden IS NULL)
			GROUP BY hash
		) latest ON latest.hash = t.hash AND latest.max_last_seen = t.last_seen
		WHERE (t.is_hidden = 0 OR t.is_hidden IS NULL)
		LIMIT 1
	`, hash).Scan(&row).Error
	if err != nil {
		return nil, err
	}
	if len(row) == 0 {
		return nil, gorm.ErrRecordNotFound
	}
	return row, nil
}

func (r *MigrateRepository) UpsertSeedParameter(record map[string]any) error {
	torrentID, ok1 := record["torrent_id"]
	siteName, ok2 := record["site_name"]
	if !ok1 || !ok2 {
		return errors.New("missing torrent_id or site_name")
	}
	return r.store.DB.Transaction(func(tx *gorm.DB) error {
		if err := tx.Table("seed_parameters").Where("torrent_id = ? AND site_name = ?", torrentID, siteName).Delete(nil).Error; err != nil {
			return err
		}
		if err := tx.Table("seed_parameters").Create(record).Error; err != nil {
			return err
		}
		return updateTorrentOfficialSiteFromSeedRecord(tx, record)
	})
}

// UpsertSeedParameterKeepingOnlyCurrent 覆盖写入当前手工编辑的种子参数，并清理同名种子的其他站点缓存。
// 参数/返回：record 必须包含 torrent_id/site_name；name 用于定位同一种子，缺失时回退到 hash；失败返回数据库错误。
// 失败场景：参数缺失、事务写入失败、清理其他站点记录失败。
// 副作用：写入 seed_parameters，并删除当前记录以外的同名或同 hash 站点参数记录。
func (r *MigrateRepository) UpsertSeedParameterKeepingOnlyCurrent(record map[string]any) error {
	torrentID := strings.TrimSpace(toString(record["torrent_id"], ""))
	siteName := strings.TrimSpace(toString(record["site_name"], ""))
	if torrentID == "" || siteName == "" {
		return errors.New("missing torrent_id or site_name")
	}
	name := strings.TrimSpace(toString(record["name"], ""))
	hash := strings.TrimSpace(toString(record["hash"], ""))

	return r.store.DB.Transaction(func(tx *gorm.DB) error {
		if err := tx.Table("seed_parameters").Where("torrent_id = ? AND site_name = ?", torrentID, siteName).Delete(nil).Error; err != nil {
			return err
		}
		if err := tx.Table("seed_parameters").Create(record).Error; err != nil {
			return err
		}
		if err := updateTorrentOfficialSiteFromSeedRecord(tx, record); err != nil {
			return err
		}

		cleanup := tx.Table("seed_parameters").Where("NOT (torrent_id = ? AND site_name = ?)", torrentID, siteName)
		switch {
		case name != "":
			cleanup = cleanup.Where("name = ?", name)
		case hash != "":
			cleanup = cleanup.Where("hash = ?", hash)
		default:
			return nil
		}
		return cleanup.Delete(nil).Error
	})
}

func (r *MigrateRepository) UpdateSeedParameterByKey(hash, torrentID, siteName string, updates map[string]any) error {
	return r.store.DB.Table("seed_parameters").Where("hash = ? AND torrent_id = ? AND site_name = ?", hash, torrentID, siteName).Updates(updates).Error
}

// UpdateSeedParameterLastPublishAt 回写 seed_parameters 的最后发布时间，优先按资源名称更新同名记录。
// 参数/返回：name 表示同一资源名称；hash/torrentID/siteName 作为兜底定位；publishAt 为发布时间；返回命中行数。
// 失败场景：仓储未初始化或数据库更新失败时返回错误。
// 副作用：写入 seed_parameters.last_publish_at。
func (r *MigrateRepository) UpdateSeedParameterLastPublishAt(name, hash, torrentID, siteName string, publishAt string) (int64, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return 0, errors.New("migrate repo is nil")
	}
	name = strings.TrimSpace(name)
	hash = strings.TrimSpace(hash)
	torrentID = strings.TrimSpace(torrentID)
	siteName = strings.TrimSpace(siteName)
	publishAt = strings.TrimSpace(publishAt)
	if publishAt == "" {
		return 0, nil
	}

	updates := map[string]any{"last_publish_at": publishAt}
	if name != "" {
		result := r.store.DB.Table("seed_parameters").
			Where("LOWER(TRIM(name)) = LOWER(TRIM(?))", name).
			Updates(updates)
		if result.Error != nil {
			return 0, result.Error
		}
		if result.RowsAffected > 0 {
			return result.RowsAffected, nil
		}
	}

	if torrentID != "" && siteName != "" {
		result := r.store.DB.Table("seed_parameters").
			Where(
				"torrent_id = ? AND (site_name = ? OR nickname = ? OR LOWER(TRIM(site_name)) = LOWER(TRIM(?)) OR LOWER(TRIM(nickname)) = LOWER(TRIM(?)))",
				torrentID,
				siteName,
				siteName,
				siteName,
				siteName,
			).
			Updates(updates)
		if result.Error != nil {
			return 0, result.Error
		}
		if result.RowsAffected > 0 {
			return result.RowsAffected, nil
		}
	}

	if hash == "" {
		return 0, nil
	}
	result := r.store.DB.Table("seed_parameters").
		Where("LOWER(TRIM(hash)) = LOWER(TRIM(?))", hash).
		Updates(updates)
	if result.Error != nil {
		return 0, result.Error
	}
	return result.RowsAffected, nil
}

// UpdateSeedParameterLastPublishAtByHash 按 hash 回写 seed_parameters 的最后发布时间。
// 参数/返回：hash 为源种子 hash，publishAt 为发布时间；返回命中行数。
// 失败场景：仓储未初始化或数据库更新失败时返回错误。
// 副作用：写入同 hash 记录的 seed_parameters.last_publish_at。
func (r *MigrateRepository) UpdateSeedParameterLastPublishAtByHash(hash string, publishAt string) (int64, error) {
	return r.UpdateSeedParameterLastPublishAt("", hash, "", "", publishAt)
}

// FindSeedPublishAtByTorrentID 查询种子的可发种时间。
// 先通过 torrent_id 找到种子名称(name)，再按 name 查询同名的所有记录中最早的 publish_at。
// 这样即使可发种时间设置在同名种子的另一个源站行(torrent_id 不同)，检查也能生效。
// 参数/返回：torrentID 为源种子 ID；返回可发种时间文本，空串表示未设置。
// 失败场景：仓储未初始化或数据库查询失败时返回错误。
// 副作用：仅读取 seed_parameters.publish_at，不修改数据。
func (r *MigrateRepository) FindSeedPublishAtByTorrentID(torrentID string) (string, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return "", errors.New("migrate repo is nil")
	}
	torrentID = strings.TrimSpace(torrentID)
	if torrentID == "" {
		return "", nil
	}
	// MySQL/PostgreSQL 中 publish_at 为日期类型，与空串比较会触发 1525 错误，仅 SQLite(TEXT) 需要判空串。
	nonEmpty := ""
	if r.store.DBType == "sqlite" {
		nonEmpty = " AND publish_at != ''"
	}

	// 先通过 torrent_id 查到种子名称，再按名称查同名所有行的最早 publish_at。
	// 使用子查询兼容 torrent_id 不存在的情况（返回空串，后续 parse 返回 false 放行）。
	row := struct {
		PublishAt *string `gorm:"column:publish_at"`
	}{}
	query := `SELECT MIN(publish_at) AS publish_at
		FROM seed_parameters
		WHERE name = (SELECT name FROM seed_parameters WHERE torrent_id = ? LIMIT 1)
			AND publish_at IS NOT NULL` + nonEmpty
	if err := r.store.DB.Raw(query, torrentID).Scan(&row).Error; err != nil {
		return "", err
	}
	if row.PublishAt == nil {
		return "", nil
	}
	return strings.TrimSpace(*row.PublishAt), nil
}

// UpdateTorrentDetailsAfterPublish 将目标站发布成功返回的详情页地址回写到 torrents.details。
// 参数/返回：hashes/name 用于定位种子，downloaderID 与 siteNickname 用于缩小命中范围；返回实际更新行数。
// 失败场景：仓储未初始化或数据库更新失败时返回错误；必要定位信息为空时返回 0。
// 副作用：写入 torrents.details，不修改下载器或其他业务表。
func (r *MigrateRepository) UpdateTorrentDetailsAfterPublish(hashes []string, name string, downloaderID string, siteNickname string, detailsURL string) (int64, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return 0, errors.New("migrate repo is nil")
	}
	cleanedHashes := compactPublishDetailHashes(hashes)
	name = strings.TrimSpace(name)
	downloaderID = strings.TrimSpace(downloaderID)
	siteNickname = strings.TrimSpace(siteNickname)
	detailsURL = strings.TrimSpace(detailsURL)
	if detailsURL == "" || (len(cleanedHashes) == 0 && name == "") {
		return 0, nil
	}

	updates := map[string]any{"details": detailsURL}
	updateBy := func(includeSite bool, build func(db *gorm.DB) *gorm.DB) (int64, error) {
		db := r.store.DB.Table("torrents").Where("(is_hidden = 0 OR is_hidden IS NULL)")
		if downloaderID != "" {
			db = db.Where("downloader_id = ?", downloaderID)
		}
		if includeSite && siteNickname != "" {
			db = db.Where("(sites = ? OR LOWER(TRIM(sites)) = LOWER(TRIM(?)))", siteNickname, siteNickname)
		}
		result := build(db).Updates(updates)
		if result.Error != nil {
			return 0, result.Error
		}
		return result.RowsAffected, nil
	}

	if len(cleanedHashes) > 0 {
		if affected, err := updateBy(true, func(db *gorm.DB) *gorm.DB {
			return db.Where("LOWER(TRIM(hash)) IN ?", cleanedHashes)
		}); err != nil || affected > 0 {
			return affected, err
		}
	}
	if name == "" || siteNickname == "" {
		return 0, nil
	}
	return updateBy(true, func(db *gorm.DB) *gorm.DB {
		return db.Where("name = ?", name)
	})
}

func compactPublishDetailHashes(values []string) []string {
	seen := map[string]struct{}{}
	result := make([]string, 0, len(values))
	for _, value := range values {
		trimmed := strings.ToLower(strings.TrimSpace(value))
		if trimmed == "" {
			continue
		}
		if _, exists := seen[trimmed]; exists {
			continue
		}
		seen[trimmed] = struct{}{}
		result = append(result, trimmed)
	}
	return result
}

// FindSeedParameterNameByTorrentID 按 torrent_id 查找唯一的 seed_parameters.name，用于发种日志缺少 name 时兜底关联。
// 参数/返回：torrentID 为源种子 ID；仅当同一 torrent_id 对应唯一非空 name 时返回该名称与 true。
// 失败场景：仓储未初始化或数据库查询失败时返回 error。
// 副作用：仅读取 seed_parameters，不修改数据。
func (r *MigrateRepository) FindSeedParameterNameByTorrentID(torrentID string) (string, bool, error) {
	if r == nil || r.store == nil || r.store.DB == nil {
		return "", false, errors.New("migrate repo is nil")
	}
	torrentID = strings.TrimSpace(torrentID)
	if torrentID == "" {
		return "", false, nil
	}

	type nameRow struct {
		Name string `gorm:"column:name"`
	}
	rows := make([]nameRow, 0)
	if err := r.store.DB.Table("seed_parameters").
		Select("name").
		Where("torrent_id = ? AND name IS NOT NULL AND TRIM(name) <> ''", torrentID).
		Group("name").
		Limit(2).
		Scan(&rows).Error; err != nil {
		return "", false, err
	}
	if len(rows) != 1 {
		return "", false, nil
	}
	name := strings.TrimSpace(rows[0].Name)
	if name == "" {
		return "", false, nil
	}
	return name, true, nil
}

func (r *MigrateRepository) ListTorrentsByNames(names []string) ([]map[string]any, error) {
	rows := make([]map[string]any, 0)
	if len(names) == 0 {
		return rows, nil
	}
	err := r.store.DB.Table("torrents").Select("name, save_path, size, downloader_id, sites, details, hash, state").Where("name IN ? AND state != ? AND (is_hidden = 0 OR is_hidden IS NULL)", names, "不存在").Scan(&rows).Error
	if err != nil {
		return nil, err
	}
	return rows, nil
}

func (r *MigrateRepository) ListSitesStatus() ([]map[string]any, error) {
	rows := make([]map[string]any, 0)
	err := r.store.DB.Table("sites").Select("nickname, site, cookie, passkey, migration").Where("nickname IS NOT NULL AND nickname != ''").Order("nickname").Scan(&rows).Error
	if err != nil {
		return nil, err
	}
	return rows, nil
}

func (r *MigrateRepository) ListBDInfoRecords(statusFilter string, limit int) ([]map[string]any, error) {
	if limit <= 0 {
		limit = 500
	}
	db := r.store.DB.Table("seed_parameters").Select("hash, torrent_id, site_name, title, nickname, mediainfo_status, bdinfo_task_id, bdinfo_started_at, bdinfo_completed_at, bdinfo_error, mediainfo")
	if statusFilter != "" {
		db = db.Where("mediainfo_status = ?", statusFilter)
	}
	rows := make([]map[string]any, 0)
	err := db.Order("updated_at DESC").Limit(limit).Scan(&rows).Error
	if err != nil {
		return nil, err
	}
	return rows, nil
}
