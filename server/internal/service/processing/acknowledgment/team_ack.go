package acknowledgment

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"unicode/utf8"

	"github.com/pt-nexus/server/internal/config"
	"github.com/pt-nexus/server/internal/platform/logx"
	"gopkg.in/yaml.v3"
)

const teamAckLogModule = "迁移-官组致谢"

type teamAckPattern struct {
	Pattern     string `yaml:"pattern"`
	Priority    int    `yaml:"priority"`
	Description string `yaml:"description"`
}

type TeamAcknowledgmentConfig struct {
	Enabled            bool             `yaml:"enabled"`
	Template           string           `yaml:"template"`
	ExcludeTeams       []string         `yaml:"exclude_teams"`
	DetectionPatterns  []teamAckPattern `yaml:"detection_patterns"`
	MaxStatementLength int              `yaml:"max_statement_length"`
	DetectionKeywords  []string         `yaml:"detection_keywords"`
	KeywordCheckLength int              `yaml:"keyword_check_length"`
}

type globalMappingsRoot struct {
	TeamAck TeamAcknowledgmentConfig `yaml:"team_acknowledgment"`
}

type SiteRow struct {
	Group       string
	Description string
}

type compiledAckPattern struct {
	Re          *regexp.Regexp
	Priority    int
	Description string
	Raw         string
}

type teamAckRuntime struct {
	Cfg      TeamAcknowledgmentConfig
	Patterns []compiledAckPattern
}

var ackRuntimeCache sync.Map
var reverseTeamCache sync.Map

// ApplyTeamAcknowledgmentIfNeeded 根据 team_acknowledgment 配置尝试补充官组致谢声明。
// 参数/返回：statement 为现有声明 BBCode；teamKey 为标准化 team.*；sites 为 sites 表的 group/description 列表；
// 返回新声明、是否插入、原因字符串（便于日志与前端回显）。
// 失败场景：配置缺失、team 被排除、无法找到显示名、或已存在声明时不会插入。
// 副作用：读取 `configs/global_mappings.yaml` 并缓存解析结果。
func ApplyTeamAcknowledgmentIfNeeded(statement string, teamKey string, sites []SiteRow) (string, bool, string) {
	rt, ok := loadTeamAckRuntime()
	if !ok || !rt.Cfg.Enabled {
		return statement, false, "未启用"
	}
	cfg := rt.Cfg

	standard := strings.TrimSpace(teamKey)
	if standard == "" {
		return statement, false, "制作组为空"
	}
	if isExcludedTeam(standard, cfg.ExcludeTeams) {
		return statement, false, "命中排除列表"
	}

	if detected, reason := detectOfficialAcknowledgment(statement, rt); detected {
		if strings.TrimSpace(reason) != "" {
			return statement, false, "声明已包含官组信息(" + reason + ")"
		}
		return statement, false, "声明已包含官组信息"
	}

	teamName := pickTeamDisplayName(standard, sites)
	if strings.TrimSpace(teamName) == "" {
		return statement, false, "未找到制作组显示名"
	}

	template := strings.TrimSpace(cfg.Template)
	if template == "" {
		template = "[quote][b][color=blue][size=5]{team_name}官组作品，感谢原制作者发布。[/size][/color][/b][/quote]"
	}
	ack := strings.ReplaceAll(template, "{team_name}", teamName)
	ack = strings.TrimSpace(ack)
	if ack == "" {
		return statement, false, "模板为空"
	}

	original := strings.TrimSpace(statement)
	if original == "" {
		return ack, true, "已插入"
	}
	return strings.TrimSpace(ack + "\n\n" + original), true, "已插入"
}

func isExcludedTeam(team string, excludes []string) bool {
	trimmed := strings.TrimSpace(team)
	if trimmed == "" {
		return true
	}
	for _, item := range excludes {
		if strings.TrimSpace(item) == trimmed {
			return true
		}
	}
	return false
}

func loadTeamAckRuntime() (teamAckRuntime, bool) {
	paths := config.ResolveRuntimePaths()
	mappingPath := strings.TrimSpace(paths.GlobalMapYML)
	if mappingPath == "" || filepath.Clean(mappingPath) == "." {
		return teamAckRuntime{}, false
	}
	cacheKey := "ackRuntime:" + mappingPath
	if cached, ok := ackRuntimeCache.Load(cacheKey); ok {
		if rt, ok := cached.(teamAckRuntime); ok {
			return rt, true
		}
	}
	data, err := os.ReadFile(mappingPath)
	if err != nil {
		logx.Debugf(teamAckLogModule, "读取官组致谢配置失败 path=%s err=%v", mappingPath, err)
		return teamAckRuntime{}, false
	}
	root := globalMappingsRoot{}
	if err := yaml.Unmarshal(data, &root); err != nil {
		logx.Debugf(teamAckLogModule, "解析官组致谢配置失败 path=%s err=%v", mappingPath, err)
		return teamAckRuntime{}, false
	}
	cfg := root.TeamAck
	if cfg.MaxStatementLength <= 0 {
		cfg.MaxStatementLength = 80
	}
	if cfg.KeywordCheckLength <= 0 {
		cfg.KeywordCheckLength = 300
	}

	compiled := compileAckPatterns(cfg.DetectionPatterns)
	rt := teamAckRuntime{
		Cfg:      cfg,
		Patterns: compiled,
	}
	ackRuntimeCache.Store(cacheKey, rt)
	return rt, true
}

func compileAckPatterns(patterns []teamAckPattern) []compiledAckPattern {
	if len(patterns) == 0 {
		return []compiledAckPattern{}
	}
	type indexed struct {
		P teamAckPattern
		I int
	}
	items := make([]indexed, 0, len(patterns))
	for i, p := range patterns {
		items = append(items, indexed{P: p, I: i})
	}
	sort.SliceStable(items, func(i, j int) bool {
		return items[i].P.Priority < items[j].P.Priority
	})

	out := make([]compiledAckPattern, 0, len(items))
	for _, item := range items {
		raw := strings.TrimSpace(item.P.Pattern)
		if raw == "" {
			continue
		}
		wrapped := raw
		// Python 使用 re.IGNORECASE|re.DOTALL，这里用内联标志对齐语义。
		if !strings.HasPrefix(raw, "(?") {
			wrapped = "(?is)" + raw
		}
		re, err := regexp.Compile(wrapped)
		if err != nil {
			logx.Debugf(teamAckLogModule, "编译官组致谢正则失败 pattern=%s desc=%s err=%v", raw, strings.TrimSpace(item.P.Description), err)
			continue
		}
		out = append(out, compiledAckPattern{
			Re:          re,
			Priority:    item.P.Priority,
			Description: strings.TrimSpace(item.P.Description),
			Raw:         raw,
		})
	}
	return out
}

func detectOfficialAcknowledgment(statement string, rt teamAckRuntime) (bool, string) {
	trimmed := strings.TrimSpace(statement)
	if trimmed == "" {
		return false, ""
	}
	cfg := rt.Cfg
	maxLen := cfg.MaxStatementLength
	if maxLen <= 0 {
		maxLen = 80
	}
	firstQuote := extractFirstQuoteBlock(trimmed)
	if firstQuote != "" {
		if utf8.RuneCountInString(firstQuote) <= maxLen {
			// 对齐 Python：按优先级逐条执行 detection_patterns；只对“第一个 quote 块”检测。
			for _, p := range rt.Patterns {
				if p.Re == nil {
					continue
				}
				if p.Re.MatchString(firstQuote) {
					if p.Description != "" {
						return true, "命中pattern:" + p.Description
					}
					return true, "命中pattern:" + p.Raw
				}
			}
		}
	}
	headerLen := cfg.KeywordCheckLength
	if headerLen <= 0 {
		headerLen = 300
	}
	runes := []rune(trimmed)
	header := trimmed
	if len(runes) > headerLen {
		header = string(runes[:headerLen])
	}
	// 对齐 Python：开头兜底仅使用 detection_keywords（例如“官组作品”），避免被“感谢/作品/官方”等通用词误判。
	for _, kw := range cfg.DetectionKeywords {
		item := strings.TrimSpace(kw)
		if item == "" {
			continue
		}
		if strings.Contains(header, item) {
			return true, "命中keyword:" + item
		}
	}
	return false, ""
}

func extractFirstQuoteBlock(statement string) string {
	lowered := strings.ToLower(statement)
	openIdx := strings.Index(lowered, "[quote")
	if openIdx < 0 {
		return ""
	}
	// 找到第一个 [quote...] 的闭合 ]
	openEnd := strings.Index(lowered[openIdx:], "]")
	if openEnd < 0 {
		return ""
	}
	openEnd = openIdx + openEnd + 1
	depth := 1
	i := openEnd
	for i < len(lowered) {
		nextOpen := strings.Index(lowered[i:], "[quote")
		nextClose := strings.Index(lowered[i:], "[/quote]")
		if nextClose < 0 {
			return ""
		}
		if nextOpen >= 0 && nextOpen < nextClose {
			depth++
			i = i + nextOpen + len("[quote")
			continue
		}
		// close
		depth--
		i = i + nextClose + len("[/quote]")
		if depth == 0 {
			return strings.TrimSpace(statement[openIdx:i])
		}
	}
	return ""
}

func pickTeamDisplayName(teamKey string, sites []SiteRow) string {
	original := reverseLookupTeamName(teamKey)
	if strings.TrimSpace(original) == "" {
		return ""
	}
	target := strings.ToLower(cleanGroupToken(original))
	if target == "" {
		return ""
	}
	for _, row := range sites {
		groupField := strings.TrimSpace(row.Group)
		if groupField == "" {
			continue
		}
		for _, token := range strings.Split(groupField, ",") {
			item := strings.ToLower(cleanGroupToken(token))
			if item != "" && item == target {
				// 返回制作组自身的显示名（来自 team.* 标准化映射），而非站点 description。
				// 合并站点（如 DS 把 DStudio/DS/DepWeb 塞进同一 group 且 description 为空）下，
				// 用 description 会导致非主组拿不到名字甚至整行被跳过。
				return original
			}
		}
	}
	// 兜底：站点表里找不到匹配行时，直接用制作组自身显示名作为致谢名，
	// 避免出现「未找到制作组显示名」而放弃写入申明。
	return original
}

func cleanGroupToken(value string) string {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return ""
	}
	trimmed = strings.Trim(trimmed, "[](){}<> ")
	trimmed = strings.TrimLeft(trimmed, "-@")
	trimmed = strings.TrimSpace(strings.TrimPrefix(strings.TrimPrefix(trimmed, "team."), "TEAM."))
	trimmed = strings.Trim(trimmed, "._- ")
	return strings.TrimSpace(trimmed)
}

func reverseLookupTeamName(teamKey string) string {
	standard := strings.TrimSpace(teamKey)
	if standard == "" {
		return ""
	}
	paths := config.ResolveRuntimePaths()
	mappingPath := strings.TrimSpace(paths.GlobalMapYML)
	if mappingPath == "" || filepath.Clean(mappingPath) == "." {
		return defaultTeamDisplayFromKey(standard)
	}
	cacheKey := "reverseTeam:" + mappingPath
	if cached, ok := reverseTeamCache.Load(cacheKey); ok {
		if table, ok := cached.(map[string]string); ok {
			if name := strings.TrimSpace(table[standard]); name != "" {
				return name
			}
			return defaultTeamDisplayFromKey(standard)
		}
	}
	data, err := os.ReadFile(mappingPath)
	if err != nil {
		return defaultTeamDisplayFromKey(standard)
	}
	reverse := buildReverseTeamFromYAML(data)
	reverseTeamCache.Store(cacheKey, reverse)
	if name := strings.TrimSpace(reverse[standard]); name != "" {
		return name
	}
	return defaultTeamDisplayFromKey(standard)
}

func defaultTeamDisplayFromKey(teamKey string) string {
	lowered := strings.ToLower(strings.TrimSpace(teamKey))
	if !strings.HasPrefix(lowered, "team.") {
		return strings.TrimSpace(teamKey)
	}
	rest := strings.TrimSpace(teamKey[5:])
	if rest == "" {
		return ""
	}
	return strings.ToUpper(rest)
}

func buildReverseTeamFromYAML(data []byte) map[string]string {
	out := map[string]string{}
	node := findYAMLMappingNodeByPath(data, []string{"global_standard_keys", "team"})
	if node == nil || node.Kind != yaml.MappingNode {
		return out
	}
	for i := 0; i+1 < len(node.Content); i += 2 {
		k := node.Content[i]
		v := node.Content[i+1]
		if k == nil || v == nil {
			continue
		}
		display := strings.TrimSpace(k.Value)
		if display == "" {
			continue
		}
		if strings.EqualFold(strings.TrimSpace(v.Tag), "!!null") {
			continue
		}
		standard := strings.TrimSpace(v.Value)
		if standard == "" {
			continue
		}
		if _, exists := out[standard]; exists {
			continue
		}
		out[standard] = display
	}
	if len(out) == 0 {
		out["team.other"] = "其他"
	}
	return out
}

func findYAMLMappingNodeByPath(data []byte, keyPath []string) *yaml.Node {
	if len(keyPath) == 0 {
		return nil
	}
	var root yaml.Node
	if err := yaml.Unmarshal(data, &root); err != nil {
		return nil
	}
	if len(root.Content) == 0 {
		return nil
	}
	node := root.Content[0]
	for _, key := range keyPath {
		if node == nil || node.Kind != yaml.MappingNode {
			return nil
		}
		next := (*yaml.Node)(nil)
		for i := 0; i+1 < len(node.Content); i += 2 {
			k := node.Content[i]
			v := node.Content[i+1]
			if k == nil || v == nil {
				continue
			}
			if strings.TrimSpace(k.Value) == key {
				next = v
				break
			}
		}
		node = next
	}
	return node
}
