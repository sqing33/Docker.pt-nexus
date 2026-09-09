package title

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"

	parser "github.com/pt-nexus/server/internal/service/acquire/extract"
)

var defaultTitleComponentKeys = []string{
	"主标题",
	"季集",
	"年份",
	"剧集状态",
	"发布版本",
	"分辨率",
	"帧率",
	"片源平台",
	"媒介",
	"HDR格式",
	"视频编码",
	"视频格式",
	"色深",
	"音频编码",
	"制作组",
	"无法识别",
}

var (
	reSeasonEpisode = regexp.MustCompile(`(?i)\bS\d{1,2}(?:E\d{1,3}(?:[-~]E?\d{1,3})?)?\b`)
	reYearToken     = regexp.MustCompile(`[\s\.\(]((?:19|20)\d{2})([\s\.\)]|$)`)
	reTechSplit     = regexp.MustCompile(`[\s\.]+`)
	reResolutionTok = regexp.MustCompile(`(?i)\b(4320p|8k|2160p|4k|1080p|1080i|720p|480p)\b`)
	reVCBVariant    = regexp.MustCompile(`(?i)^(.+?)-([\w\s]+&VCB-Studio)$`)
	reBDRipToken    = regexp.MustCompile(`(?i)\bBD[-\s]?RIP\b`)
	reTVRipToken    = regexp.MustCompile(`(?i)\bTV[-\s]?RIP\b`)
	reDVDRipToken   = regexp.MustCompile(`(?i)\bDVD[-\s]?RIP\b`)
	reDVDDiscToken  = regexp.MustCompile(`(?i)\bDVD(?:5|9)\b`)
)

var specialReleaseGroupSuffixes = []string{"mUHD-FRDS", "MNHD-FRDS", "￡cXcY-FRDS", "DMG&VCB-Studio", "VCB-Studio"}

const sourcePlatformAlternatives = `MA|Apple\s?TV\+|ViuTV|MyTVSuper|MyTVS|DNSP|iT|NowE|MyVideo|TWN|LiTV|TVBAnywhere|DMM|iPad|TX|iQIYI|MUBI|TVB|YOUKU|NowPlay|AMZN|Amazon|Netflix|NF|DSNP|MAX|HMAX|HULU|ATVP|iTunes|friDay|USA|EUR|JPN|CEE|FRA|LINETV|PCOK|Hami|GBR|NowPlayer|CR|Crunchyroll|SEEZN|GER|CAN|CHN|Viu|WeTV|meWATCH|CATCHPLAY|AMC\+|TVING|Baha|KKTV|IQ|HKG|ITA|ESP|Disney\+|Disney`

var (
	reSourcePlatformBoundary = regexp.MustCompile("(?i)(?:^|[^\\p{L}\\p{N}_])(" + sourcePlatformAlternatives + ")(?:$|[^\\p{L}\\p{N}_])")
	reAudioDTSHDMA           = regexp.MustCompile(`(?i)\bDTS[-\s]?HD\s*MA\b`)
	reAudioCodecDD           = regexp.MustCompile(`(?i)\bDD\b`)
	reReleaseGroupSplit      = regexp.MustCompile(`[@\-\s]+`)
	reHDRTitleToken          = regexp.MustCompile(`(?i)Dolby Vision|DoVi|HDR10\+|HDRVivid|HDR10|HLG|HDR|SDR|EDR|DV|Vivid`)
)

// BuildSimpleTitleComponents 构建标题组件（不使用媒体文本纠偏）。
// 参数/返回：title 为原始标题，releaseGroup 为外部制作组；返回有序组件数组。
// 失败场景：标题为空时返回空切片。
// 副作用：无。
func BuildSimpleTitleComponents(title string, releaseGroup string) []map[string]any {
	return BuildSimpleTitleComponentsWithMediaInfo(title, releaseGroup, "")
}

// BuildSimpleTitleComponentsWithMediaInfo 构建标题组件并按媒介类型纠偏视频编码。
// 参数/返回：mediaInfo 可为空；返回统一结构的标题组件数组。
// 失败场景：标题为空时返回空切片。
// 副作用：无。
func BuildSimpleTitleComponentsWithMediaInfo(title string, releaseGroup string, mediaInfo string) []map[string]any {
	trimmed := strings.TrimSpace(title)
	if trimmed == "" {
		return []map[string]any{}
	}
	sanitizedMediaInfo := parser.SanitizeMediaTextForAnalysis(mediaInfo)

	// 与 Python 的 upload_data_title 行为对齐：优先按 title 中的 "-" / "@" 做制作组切分，
	// 这会导致诸如 WEB-DL / DTS-HD 等标题把后半段误识别为制作组，但可以确保 Go 侧输出与 Python 一致。
	titlePart, team := splitTitleAndTeamPythonish(trimmed, releaseGroup)

	values := map[string]string{}
	if team != "" {
		values["制作组"] = team
	}

	// 季集提取与移除。
	if seasonEpisode, updated := extractSeasonEpisodeAndRemove(titlePart); seasonEpisode != "" {
		values["季集"] = seasonEpisode
		titlePart = updated
	}

	// 片源平台提取需要保留年份信息，以对齐 Python 的“存在年份时只在技术标签区域提取”逻辑。
	titlePartWithYear := titlePart

	// 年份提取与移除（Python 规则：要求年份前后有分隔符）。
	if year, updated := extractYearAndRemove(titlePart); year != "" {
		values["年份"] = year
		titlePart = updated
	}

	// 剪辑版本提取并拼接到年份（对齐 Python）。
	if cut, updated := extractCutVersionAndRemove(titlePart); cut != "" {
		if y := strings.TrimSpace(values["年份"]); y != "" {
			values["年份"] = strings.TrimSpace(y + " " + cut)
		} else {
			values["年份"] = cut
		}
		titlePart = updated
	}

	// 对齐 Python：在提取技术标签前，对视频编码 token 做容错修正（H264 -> H.264 等缺点号情况）。
	titlePart = normalizeTitleVideoCodecTokens(titlePart)
	titlePartWithYear = normalizeTitleVideoCodecTokens(titlePartWithYear)

	// 对齐 Python：在提取技术标签前，对音频相关 token 做容错修正（缺空格/缺小数点/单复数）。
	titlePart = normalizeTitleAudioTokens(titlePart)
	titlePartWithYear = normalizeTitleAudioTokens(titlePartWithYear)

	// 其余技术参数提取以“去掉制作组/年份/季集后的 titlePart”为准。
	if completion := extractCompletionStatusFromTitle(titlePart); completion != "" {
		values["剧集状态"] = completion
	}
	if releaseVersion := extractReleaseVersionFromTitle(titlePart); releaseVersion != "" {
		values["发布版本"] = releaseVersion
	}
	if resolution := extractResolutionFromTitle(titlePart); resolution != "" {
		values["分辨率"] = resolution
	}
	if platform := extractSourcePlatformFromTitle(titlePartWithYear, team); platform != "" {
		values["片源平台"] = platform
	}
	if medium := extractMediumPythonish(titlePart); medium != "" {
		modifier := extractQualityModifierFromTitle(titlePart)
		if modifier != "" && !containsTokenFold(medium, modifier) {
			values["媒介"] = strings.TrimSpace(medium + " " + modifier)
		} else {
			values["媒介"] = medium
		}
	}
	if videoCodec := extractVideoCodecFromTitle(titlePart); videoCodec != "" {
		values["视频编码"] = videoCodec
	}
	normalizeVideoCodecByMedium(values, sanitizedMediaInfo)
	if videoFormat := extractVideoFormatFromTitle(titlePart); videoFormat != "" {
		values["视频格式"] = videoFormat
	}
	if hdr := extractHDRFormatFromTitle(titlePart); hdr != "" {
		values["HDR格式"] = hdr
	}
	if bitDepth := extractBitDepthFromTitle(titlePart); bitDepth != "" {
		values["色深"] = bitDepth
	}
	if frameRate := extractFrameRateFromTitle(titlePart); frameRate != "" {
		values["帧率"] = frameRate
	}
	if audio := extractAudioFromTitle(titlePart); audio != "" {
		values["音频编码"] = audio
	}

	// 主标题与无法识别字段对齐 Python：从第一个技术标签开始切分 titleZone / techZone，
	// techZone 去掉已识别标签后剩余内容作为“无法识别”。
	mainTitle, unrecognized := extractMainTitleAndUnrecognized(titlePart, values)
	if strings.TrimSpace(mainTitle) == "" {
		mainTitle = strings.TrimSpace(titlePart)
	}
	values["主标题"] = mainTitle
	if strings.TrimSpace(unrecognized) != "" {
		values["无法识别"] = unrecognized
	}

	return buildOrderedTitleComponents(values)
}

func splitTitleAndTeamPythonish(title string, releaseGroup string) (string, string) {
	trimmed := strings.TrimSpace(title)
	team := strings.TrimSpace(releaseGroup)
	if team != "" {
		return trimmed, team
	}
	if trimmed == "" {
		return "", ""
	}

	for _, group := range specialReleaseGroupSuffixes {
		if strings.HasSuffix(trimmed, " "+group) {
			return strings.TrimSpace(trimmed[:len(trimmed)-len(group)-1]), group
		}
		if strings.HasSuffix(trimmed, "-"+group) {
			return strings.TrimSpace(trimmed[:len(trimmed)-len(group)-1]), group
		}
		if strings.HasPrefix(group, "￡") && strings.HasSuffix(trimmed, group) {
			return strings.TrimSpace(trimmed[:len(trimmed)-len(group)]), group
		}
	}

	// VCB-Studio 变体制作组
	if m := reVCBVariant.FindStringSubmatch(trimmed); len(m) == 3 {
		return strings.TrimSpace(m[1]), strings.TrimSpace(m[2])
	}

	// 通用模式：选择最早出现且后半段无空白字符的 "-" / "@"，以对齐 Python 的非贪婪匹配行为。
	for idx := 0; idx < len(trimmed); idx++ {
		ch := trimmed[idx]
		if ch != '-' && ch != '@' {
			continue
		}
		before := strings.TrimSpace(trimmed[:idx])
		after := strings.TrimSpace(trimmed[idx+1:])
		if before == "" || after == "" {
			continue
		}
		if strings.ContainsAny(after, " \t\r\n") {
			continue
		}
		return before, after
	}

	return trimmed, ""
}

func extractSeasonEpisodeAndRemove(title string) (string, string) {
	if title == "" {
		return "", title
	}
	loc := reSeasonEpisode.FindStringIndex(title)
	if loc == nil {
		return "", title
	}
	raw := title[loc[0]:loc[1]]
	season := strings.ToUpper(strings.ReplaceAll(raw, " ", ""))
	updated := strings.TrimSpace(title[:loc[0]] + " " + title[loc[1]:])
	updated = strings.Join(strings.Fields(updated), " ")
	return season, updated
}

func extractYearAndRemove(title string) (string, string) {
	if title == "" {
		return "", title
	}
	m := reYearToken.FindStringSubmatch(title)
	if len(m) < 2 {
		return "", title
	}
	year := strings.TrimSpace(m[1])
	if year == "" {
		return "", title
	}
	reRemove := regexp.MustCompile(`[\s\.\(]` + regexp.QuoteMeta(year) + `([\s\.\)]|$)`)
	updated := reRemove.ReplaceAllString(title, " ")
	updated = strings.Join(strings.Fields(updated), " ")
	return year, strings.TrimSpace(updated)
}

func extractMediumPythonish(title string) string {
	upper := strings.ToUpper(title)
	parts := make([]string, 0, 6)

	if regexp.MustCompile(`(?i)\bUHDTV\b`).FindStringIndex(title) != nil {
		parts = append(parts, "UHDTV")
	}

	if regexp.MustCompile(`(?i)\bHDTV\b`).FindStringIndex(title) != nil {
		parts = append(parts, "HDTV")
	}

	if strings.Contains(upper, "UHD") {
		parts = append(parts, "UHD")
	}

	blurayToken := PreferredBlurayTokenFromTitle(title)
	if blurayToken != "" {
		if regexp.MustCompile(`(?i)\bDIY\b`).FindStringIndex(title) != nil {
			parts = append(parts, blurayToken+" DIY")
		} else {
			parts = append(parts, blurayToken)
		}
	}

	if strings.Contains(upper, "REMUX") {
		parts = append(parts, "Remux")
	}

	if reBDRipToken.MatchString(title) {
		parts = append(parts, "BDRip")
	}

	if raw := strings.TrimSpace(reTVRipToken.FindString(title)); raw != "" {
		parts = append(parts, normalizeMediumToken(raw))
	}

	if raw := strings.TrimSpace(reDVDRipToken.FindString(title)); raw != "" {
		parts = append(parts, normalizeMediumToken(raw))
	}

	if raw := strings.TrimSpace(reDVDDiscToken.FindString(title)); raw != "" {
		parts = append(parts, strings.ToUpper(raw))
	}

	// WEB 类媒介保持原始语义（仅当标题中明确出现 WEB-DL/WEBRIP 等）。
	if strings.Contains(upper, "WEB-DL") || strings.Contains(upper, "WEBDL") {
		parts = append(parts, "WEB-DL")
	} else if strings.Contains(upper, "WEBRIP") {
		parts = append(parts, "WEBRip")
	}

	return strings.Join(parts, " ")
}

func normalizeMediumToken(raw string) string {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return ""
	}
	switch {
	case reTVRipToken.MatchString(trimmed):
		return "TVRip"
	case reDVDRipToken.MatchString(trimmed):
		return "DVDRip"
	default:
		return regexp.MustCompile(`[\s\.]+`).ReplaceAllString(trimmed, " ")
	}
}

func containsTokenFold(text string, token string) bool {
	trimmedText := strings.TrimSpace(text)
	trimmedToken := strings.TrimSpace(token)
	if trimmedText == "" || trimmedToken == "" {
		return false
	}
	for _, item := range strings.Fields(trimmedText) {
		if strings.EqualFold(strings.TrimSpace(item), trimmedToken) {
			return true
		}
	}
	return false
}

func extractMainTitleAndUnrecognized(titlePart string, values map[string]string) (string, string) {
	trimmed := strings.TrimSpace(titlePart)
	if trimmed == "" {
		return "", ""
	}

	techStart := len(trimmed)

	// 对齐 Python：从第一个技术标签开始切分 titleZone / techZone。
	// 这里基于已识别到的字段值尽量估算最早技术标签位置（避免仅靠分辨率导致切分偏后）。
	candidates := []string{
		values["剧集状态"],
		values["发布版本"],
		values["分辨率"],
		values["帧率"],
		values["片源平台"],
		values["媒介"],
		values["HDR格式"],
		values["视频编码"],
		values["视频格式"],
		values["色深"],
		values["音频编码"],
	}
	upper := strings.ToUpper(trimmed)
	for _, cand := range candidates {
		cand = strings.TrimSpace(cand)
		if cand == "" {
			continue
		}
		if idx := strings.Index(upper, strings.ToUpper(cand)); idx >= 0 {
			techStart = minInt(techStart, idx)
		}
	}
	// 兜底：如果找到分辨率，仍然取其位置作为潜在切分点
	if idx := reResolutionTok.FindStringIndex(trimmed); idx != nil {
		techStart = minInt(techStart, idx[0])
	}
	if techStart < 0 || techStart > len(trimmed) {
		techStart = len(trimmed)
	}

	titleZone := strings.TrimSpace(trimmed[:techStart])
	techZone := strings.TrimSpace(trimmed[techStart:])

	mainTitle := strings.TrimSpace(reTechSplit.ReplaceAllString(titleZone, " "))

	// 识别到的标签集合，用于从 techZone 中移除后得到“无法识别”。
	found := make([]string, 0, 12)
	if v := strings.TrimSpace(values["分辨率"]); v != "" {
		found = append(found, v)
	}
	if strings.Contains(strings.ToUpper(titlePart), "UHD") {
		found = append(found, "UHD")
	}
	if tok := PreferredBlurayTokenFromTitle(titlePart); tok != "" {
		found = append(found, tok)
	}
	if strings.Contains(strings.ToUpper(titlePart), "REMUX") {
		found = append(found, "REMUX")
	}
	if strings.Contains(strings.ToUpper(titlePart), "WEB-DL") || strings.Contains(strings.ToUpper(titlePart), "WEBDL") {
		found = append(found, "WEB-DL")
	} else if strings.Contains(strings.ToUpper(titlePart), "WEBRIP") {
		found = append(found, "WEBRip")
	}
	if match := strings.TrimSpace(reBDRipToken.FindString(titlePart)); match != "" {
		// BDRip 兼容变体（BDrip/BD-Rip/BD Rip）统一从“无法识别”清理集合中移除。
		found = append(found, match, "BDRip", "BD-Rip", "BD Rip", "BDrip")
	}
	if v := strings.TrimSpace(values["媒介"]); v != "" {
		found = append(found, mediumCleanupTags(v)...)
	}
	if v := strings.TrimSpace(values["剧集状态"]); v != "" {
		found = append(found, v)
	}
	if v := strings.TrimSpace(values["发布版本"]); v != "" {
		found = append(found, v)
	}
	if v := strings.TrimSpace(values["片源平台"]); v != "" {
		found = append(found, v)
	}
	if v := strings.TrimSpace(values["HDR格式"]); v != "" {
		found = append(found, hdrCleanupTags(v)...)
	}
	if v := strings.TrimSpace(values["视频格式"]); v != "" {
		found = append(found, v)
	}
	if v := strings.TrimSpace(values["色深"]); v != "" {
		found = append(found, v)
	}
	if v := strings.TrimSpace(values["帧率"]); v != "" {
		found = append(found, v)
	}
	if v := strings.TrimSpace(values["视频编码"]); v != "" {
		found = append(found, videoCodecCleanupTags(v)...)
	}
	if v := strings.TrimSpace(values["音频编码"]); v != "" {
		// 对齐 Python：清理“无法识别”时优先移除完整音频标签，并补充声道/Atmos/音轨数 token。
		found = append(found, audioCleanupTags(v)...)
	}

	// 先移除长标签，避免短标签破坏长标签的结构（对齐 Python sorted(..., key=len, reverse=True)）。
	sort.Slice(found, func(i, j int) bool { return len(found[i]) > len(found[j]) })

	cleaned := techZone
	for _, tag := range found {
		tag = strings.TrimSpace(tag)
		if tag == "" {
			continue
		}
		// 片源平台 token 可能包含非单词字符（例如 Apple TV+ / AMC+），这里用更稳健的边界规则移除。
		var compiled *regexp.Regexp
		if strings.EqualFold(tag, strings.TrimSpace(values["片源平台"])) {
			compiled = regexp.MustCompile(`(?i)(?:^|[^\p{L}\p{N}_])` + regexp.QuoteMeta(tag) + `(?:$|[^\p{L}\p{N}_])`)
		} else {
			// Go regexp (RE2) 不支持 lookahead，这里用 \b...\b 近似 Python 的 \b...(?!\w) 行为。
			compiled = regexp.MustCompile(`(?i)\b` + regexp.QuoteMeta(tag) + `\b`)
		}
		cleaned = compiled.ReplaceAllString(cleaned, " ")
	}

	remains := reTechSplit.Split(cleaned, -1)
	uniq := make(map[string]struct{}, 8)
	out := make([]string, 0, 8)
	for _, item := range remains {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}
		if _, ok := uniq[item]; ok {
			continue
		}
		uniq[item] = struct{}{}
		out = append(out, item)
	}
	sort.Strings(out)
	return mainTitle, strings.TrimSpace(strings.Join(out, " "))
}

func audioCleanupTags(audio string) []string {
	trimmed := strings.TrimSpace(audio)
	if trimmed == "" {
		return nil
	}

	seen := make(map[string]struct{}, 8)
	out := make([]string, 0, 8)
	appendTag := func(tag string) {
		tag = strings.TrimSpace(tag)
		if tag == "" {
			return
		}
		if _, ok := seen[tag]; ok {
			return
		}
		seen[tag] = struct{}{}
		out = append(out, tag)
	}

	appendTag(trimmed)

	codecPatterns := []string{
		"DTS-HD MA",
		"DTS-HD HR",
		"DTS:X",
		"TrueHD",
		"DTS",
		"DDP",
		"DD",
		"AC3",
		"FLAC",
		"AAC",
		"LPCM",
		"AV3A",
		"ALAC",
		"APE",
		"WAV",
		"OGG",
		"DSD",
		"Opus",
		"MP3",
		"Dual",
	}
	upper := strings.ToUpper(trimmed)
	for _, codec := range codecPatterns {
		if strings.Contains(upper, strings.ToUpper(codec)) {
			appendTag(codec)
			break
		}
	}

	channelRe := regexp.MustCompile(`(?i)\b(\d{1,2}\.\d(?:\.\d+)?)\b`)
	channelMatches := channelRe.FindAllStringSubmatch(trimmed, -1)
	for _, match := range channelMatches {
		if len(match) >= 2 {
			appendTag(match[1])
		}
	}

	if strings.Contains(upper, "ATMOS") {
		appendTag("Atmos")
	}

	audioCountRe := regexp.MustCompile(`(?i)\b(\d+\s*Audios?)\b`)
	audioCountMatches := audioCountRe.FindAllStringSubmatch(trimmed, -1)
	for _, match := range audioCountMatches {
		if len(match) < 2 {
			continue
		}
		appendTag(match[1])
		appendTag(strings.ReplaceAll(match[1], " ", ""))
	}

	return out
}

func mediumCleanupTags(medium string) []string {
	trimmed := strings.TrimSpace(medium)
	if trimmed == "" {
		return nil
	}

	seen := make(map[string]struct{}, 10)
	out := make([]string, 0, 10)
	appendTag := func(tag string) {
		tag = strings.TrimSpace(tag)
		if tag == "" {
			return
		}
		key := strings.ToUpper(tag)
		if _, ok := seen[key]; ok {
			return
		}
		seen[key] = struct{}{}
		out = append(out, tag)
	}

	appendTag(trimmed)
	for _, token := range strings.Fields(trimmed) {
		appendTag(token)
	}

	switch {
	case regexp.MustCompile(`(?i)\bUHDTV\b`).FindStringIndex(trimmed) != nil:
		appendTag("UHDTV")
	case regexp.MustCompile(`(?i)\bHDTV\b`).FindStringIndex(trimmed) != nil:
		appendTag("HDTV")
	}

	if regexp.MustCompile(`(?i)\bBlu[-\s]?ray\b`).FindStringIndex(trimmed) != nil {
		appendTag("Blu-ray")
		appendTag("BluRay")
		appendTag("BLURAY")
	}
	if regexp.MustCompile(`(?i)\bTV[-\s]?Rip\b`).FindStringIndex(trimmed) != nil {
		appendTag("TVRip")
		appendTag("TV-Rip")
		appendTag("TV Rip")
	}
	if regexp.MustCompile(`(?i)\bDVD[-\s]?Rip\b`).FindStringIndex(trimmed) != nil {
		appendTag("DVDRip")
		appendTag("DVD-Rip")
		appendTag("DVD Rip")
	}
	if regexp.MustCompile(`(?i)\bDVD(?:5|9)\b`).FindStringIndex(trimmed) != nil {
		appendTag("DVD5")
		appendTag("DVD9")
	}
	if regexp.MustCompile(`(?i)\bWEB[-\s]?DL\b`).FindStringIndex(trimmed) != nil {
		appendTag("WEB-DL")
		appendTag("WEBDL")
	}
	if regexp.MustCompile(`(?i)\bWEBRIP\b`).FindStringIndex(trimmed) != nil {
		appendTag("WEBRip")
		appendTag("WEBRIP")
	}
	if regexp.MustCompile(`(?i)\bBD[-\s]?Rip\b`).FindStringIndex(trimmed) != nil {
		appendTag("BDRip")
		appendTag("BD-Rip")
		appendTag("BD Rip")
	}

	return out
}

func videoCodecCleanupTags(codec string) []string {
	trimmed := strings.TrimSpace(codec)
	if trimmed == "" {
		return nil
	}

	seen := make(map[string]struct{}, 5)
	out := make([]string, 0, 5)
	appendTag := func(tag string) {
		tag = strings.TrimSpace(tag)
		if tag == "" {
			return
		}
		key := strings.ToUpper(tag)
		if _, ok := seen[key]; ok {
			return
		}
		seen[key] = struct{}{}
		out = append(out, tag)
	}

	switch detectVideoCodecFamily(trimmed) {
	case "h265":
		for _, tag := range []string{trimmed, "HEVC", "H.265", "H265", "x265"} {
			appendTag(tag)
		}
	case "h264":
		for _, tag := range []string{trimmed, "AVC", "H.264", "H264", "x264"} {
			appendTag(tag)
		}
	default:
		appendTag(trimmed)
		switch {
		case strings.EqualFold(trimmed, "VP9"):
			appendTag("VP9")
		case strings.EqualFold(trimmed, "AVS2"):
			appendTag("AVS2")
		}
	}

	return out
}

func splitTitleAndTeam(title string, releaseGroup string) (string, string) {
	mainTitle, team := splitTitleAndTeamPythonish(title, releaseGroup)
	return strings.TrimSpace(mainTitle), strings.TrimSpace(parser.NormalizeTeamLabel(team))
}

func isSpaceSeparatedReleaseGroup(group string) bool {
	switch strings.TrimSpace(group) {
	case "MNHD-FRDS", "mUHD-FRDS", "￡cXcY-FRDS":
		return true
	default:
		return false
	}
}

func extractCompletionStatusFromTitle(title string) string {
	if strings.TrimSpace(title) == "" {
		return ""
	}
	// 对齐 Python：仅提取 Complete/COMPLETE，并返回命中的原始文本，不做本地化翻译。
	re := regexp.MustCompile(`(?i)(?:^|[^\p{L}\p{N}_])(Complete)(?:$|[^\p{L}\p{N}_])`)
	match := re.FindStringSubmatch(title)
	if len(match) >= 2 {
		return match[1]
	}
	return ""
}

func extractReleaseVersionFromTitle(title string) string {
	pairs := []struct {
		pattern *regexp.Regexp
		label   string
	}{
		{regexp.MustCompile(`(?i)\bREPACK\b`), "REPACK"},
		{regexp.MustCompile(`(?i)\bRERIP\b`), "RERIP"},
		{regexp.MustCompile(`(?i)\bPROPER\b`), "PROPER"},
		{regexp.MustCompile(`(?i)\bREPOST\b`), "REPOST"},
		{regexp.MustCompile(`(?i)\bEXTENDED\b`), "Extended"},
		{regexp.MustCompile(`(?i)\bUNCUT\b`), "Uncut"},
		{regexp.MustCompile(`(?i)\bHYBRID\b`), "Hybrid"},
		{regexp.MustCompile(`(?i)\bIMAX\b`), "IMAX"},
		{regexp.MustCompile(`(?i)\bREMASTER(?:ED)?\b`), "Remastered"},
		{regexp.MustCompile(`(?i)DIRECTOR['’]?S?\s*CUT`), "Director's Cut"},
		{regexp.MustCompile(`(?i)\bV\d+\b`), strings.ToUpper(strings.TrimSpace(regexp.MustCompile(`(?i)\bV\d+\b`).FindString(title)))},
	}
	parts := make([]string, 0, 2)
	for _, pair := range pairs {
		if pair.pattern.MatchString(title) && strings.TrimSpace(pair.label) != "" {
			parts = append(parts, pair.label)
		}
	}
	return strings.Join(parts, " ")
}

func extractCutVersionAndRemove(title string) (string, string) {
	trimmed := strings.TrimSpace(title)
	if trimmed == "" {
		return "", title
	}

	// 对齐 Python 的 cut_version_pattern（不求每个别名都完全一致，但覆盖主要变体）。
	re := regexp.MustCompile(`(?i)(?:^|[^\p{L}\p{N}_])(Theatrical[\s\.]?Cut|Directors?[\s\.]?Cut|DC|Extended(?:[\s\.]?(?:Cut|Edition))?|Final[\s\.]?Cut|Anniversary[\s\.]?Edition|Restored|Remastered|Criterion[\s\.]?(?:Edition|Collection)|Ultimate[\s\.]?Cut|IMAX[\s\.]?Edition|Open[\s\.]?Matte|Unrated(?:[\s\.]?Cut)?)(?:$|[^\p{L}\p{N}_])`)
	m := re.FindStringSubmatchIndex(trimmed)
	if m == nil || len(m) < 4 {
		return "", title
	}

	raw := strings.TrimSpace(trimmed[m[2]:m[3]])
	if raw == "" {
		return "", title
	}

	normalized := regexp.MustCompile(`[\s\.]+`).ReplaceAllString(raw, " ")
	updated := strings.TrimSpace(trimmed[:m[0]] + " " + trimmed[m[1]:])
	updated = strings.Join(strings.Fields(updated), " ")
	return strings.TrimSpace(normalized), updated
}

func extractQualityModifierFromTitle(title string) string {
	upper := strings.ToUpper(title)
	switch {
	case strings.Contains(upper, "MAXPLUS"):
		return "MAXPLUS"
	case strings.Contains(upper, "MINIBD"):
		return "MiniBD"
	case strings.Contains(upper, "REMUX"):
		return "Remux"
	case strings.Contains(upper, "HFR"):
		return "HFR"
	case strings.Contains(upper, "HQ"):
		return "HQ"
	default:
		return ""
	}
}

func extractResolutionFromTitle(title string) string {
	re := regexp.MustCompile(`(?i)\b(4320p|8k|2160p|4k|1080p|1080i|720p|480p)\b`)
	match := strings.TrimSpace(re.FindString(title))
	if match == "" {
		return ""
	}
	// 对齐 Python：保持标题中匹配到的原始分辨率 token（如 4K 保持 4K，不转换为 2160P）。
	return match
}

func normalizeVideoCodecByMedium(values map[string]string, mediaInfo string) {
	if values == nil {
		return
	}

	medium := strings.TrimSpace(values["媒介"])
	if medium == "" {
		return
	}
	sourceType := classifySourceFromMedium(medium)
	if sourceType == "" {
		return
	}

	current := strings.TrimSpace(values["视频编码"])
	family := detectVideoCodecFamily(current, mediaInfo)
	if family == "" {
		return
	}

	targetMap := map[string]map[string]string{
		"disc":  {"h264": "AVC", "h265": "HEVC"},
		"webdl": {"h264": "H.264", "h265": "H.265"},
		"rip":   {"h264": "x264", "h265": "x265"},
	}

	if target, ok := targetMap[sourceType]; ok {
		if codec, ok := target[family]; ok && strings.TrimSpace(codec) != "" {
			values["视频编码"] = codec
		}
	}
}

// PreferExplicitTitleMedium 在当前媒介为空、其他或压制时，优先采用标题中明确识别出的媒介。
// 参数/返回：currentMedium 为已有标准媒介键；title 与 mediaInfo 用于提取标题中的明确媒介；返回修正后的媒介键。
// 失败场景：标题无法识别出明确媒介时保留 currentMedium。
// 副作用：无。
func PreferExplicitTitleMedium(currentMedium, title, mediaInfo string) string {
	current := strings.TrimSpace(currentMedium)

	// 标题显式声明 WEB-DL/WEBDL 时，媒介强制为 WEB-DL。
	// 即便来源站点把媒介判成 Encode（例如 WEB-DL 源被 x264 重新编码，mediainfo 出现 x264 编码参数），
	// 也以标题声明的源为准，避免媒介被误判为压制。此规则优先级高于 weak 判断，可覆盖 medium.encode / medium.encode_1080p 等非空媒介。
	if titleDeclaresWebDL(title) {
		return "medium.webdl"
	}

	if !isWeakMediumValue(current) {
		return current
	}

	inferred := parser.InferStandardizedValues(strings.TrimSpace(title), strings.TrimSpace(mediaInfo), "")
	if medium := strings.TrimSpace(inferred["medium"]); medium != "" {
		return medium
	}
	return current
}

// titleDeclaresWebDL 判断标题是否显式声明了 WEB-DL 源（兼容 WEB-DL / WEBDL 写法，与 extractMediumPythonish 保持一致）。
func titleDeclaresWebDL(title string) bool {
	upper := strings.ToUpper(strings.TrimSpace(title))
	return strings.Contains(upper, "WEB-DL") || strings.Contains(upper, "WEBDL")
}

func isWeakMediumValue(medium string) bool {
	switch strings.ToLower(strings.TrimSpace(medium)) {
	case "", "medium.other", "medium.encode", "encode", "other":
		return true
	default:
		return false
	}
}

func detectVideoCodecFamily(candidates ...string) string {
	combined := strings.Join(candidates, " ")
	combined = strings.TrimSpace(combined)
	if combined == "" {
		return ""
	}

	reH265 := regexp.MustCompile(`(?i)\b(HEVC|x265|H\s*\.?\s*265)\b`)
	reH264 := regexp.MustCompile(`(?i)\b(AVC|x264|H\s*\.?\s*264)\b`)

	hasH265 := reH265.FindStringIndex(combined) != nil
	hasH264 := reH264.FindStringIndex(combined) != nil

	if hasH265 && !hasH264 {
		return "h265"
	}
	if hasH264 && !hasH265 {
		return "h264"
	}
	return ""
}

func classifySourceFromMedium(medium string) string {
	if strings.TrimSpace(medium) == "" {
		return ""
	}
	m := medium

	if regexp.MustCompile(`(?i)\bWEB[-\s]?DL\b`).FindStringIndex(m) != nil {
		return "webdl"
	}
	if regexp.MustCompile(`(?i)\b(?:UHDTV|HDTV)\b`).FindStringIndex(m) != nil {
		return "webdl"
	}
	if regexp.MustCompile(`(?i)\bTV[-\s]?RIP\b`).FindStringIndex(m) != nil {
		return "rip"
	}
	if regexp.MustCompile(`(?i)\bDVD[-\s]?RIP\b`).FindStringIndex(m) != nil {
		return "rip"
	}
	if regexp.MustCompile(`(?i)\bRemux\b`).FindStringIndex(m) != nil {
		return "disc"
	}
	// Python 约定：BluRay 视为压制
	if regexp.MustCompile(`(?i)\bBluRay\b`).FindStringIndex(m) != nil {
		return "rip"
	}
	if regexp.MustCompile(`(?i)rip`).FindStringIndex(m) != nil {
		return "rip"
	}
	// 盘源（Blu-ray / UHD Blu-ray 等）
	if regexp.MustCompile(`(?i)\b(UHD\s*Blu[-\s]ray|Blu[-\s]ray)\b`).FindStringIndex(m) != nil {
		return "disc"
	}

	return ""
}

func extractSourcePlatformFromTitle(title string, releaseGroup string) string {
	trimmed := strings.TrimSpace(title)
	if trimmed == "" {
		return ""
	}

	searchText := trimmed

	// Python 对 source_platform 做了位置限制：当标题存在年份时，仅在年份/分辨率之后的技术标签区域提取。
	if loc := reYearToken.FindStringSubmatchIndex(trimmed); loc != nil {
		techStart := loc[1]
		if resLoc := reResolutionTok.FindStringIndex(trimmed); resLoc != nil && resLoc[1] < techStart {
			techStart = resLoc[1]
		}
		if techStart >= 0 && techStart <= len(trimmed) {
			searchText = trimmed[techStart:]
		}
	}

	searchText = maskAudioMAForSourcePlatform(searchText)

	releaseGroupKeywords := splitReleaseGroupKeywords(releaseGroup)

	matches := reSourcePlatformBoundary.FindAllStringSubmatchIndex(searchText, -1)
	for _, m := range matches {
		if len(m) < 4 {
			continue
		}
		value := strings.TrimSpace(searchText[m[2]:m[3]])
		if value == "" {
			continue
		}
		if isReleaseGroupKeyword(value, releaseGroupKeywords) {
			continue
		}
		return value
	}

	return ""
}

func maskAudioMAForSourcePlatform(text string) string {
	if strings.TrimSpace(text) == "" {
		return text
	}
	// 避免把音频的 “DTS-HD MA” 中的 MA 误识别为片源平台 token（MA）。
	return reAudioDTSHDMA.ReplaceAllString(text, "DTS-HD")
}

func splitReleaseGroupKeywords(releaseGroup string) []string {
	releaseGroup = strings.TrimSpace(releaseGroup)
	if releaseGroup == "" {
		return nil
	}
	parts := reReleaseGroupSplit.Split(releaseGroup, -1)
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		out = append(out, p)
	}
	return out
}

func isReleaseGroupKeyword(value string, keywords []string) bool {
	if value == "" || len(keywords) == 0 {
		return false
	}
	for _, kw := range keywords {
		if strings.EqualFold(value, kw) {
			return true
		}
	}
	return false
}

func extractVideoCodecFromTitle(title string) string {
	upper := strings.ToUpper(title)
	switch {
	case strings.Contains(upper, "AV1"):
		return "AV1"
	case strings.Contains(upper, "VP9"), strings.Contains(upper, "VP8"):
		return "VP9"
	case strings.Contains(upper, "AVS2"):
		return "AVS2"
	case strings.Contains(upper, "X265"):
		return "x265"
	case strings.Contains(upper, "H.265"), strings.Contains(upper, "H265"), strings.Contains(upper, "HEVC"):
		return "HEVC"
	case strings.Contains(upper, "X264"):
		return "x264"
	case strings.Contains(upper, "H.264"), strings.Contains(upper, "H264"), strings.Contains(upper, "AVC"):
		return "AVC"
	case strings.Contains(upper, "VC-1"), strings.Contains(upper, "VC1"):
		return "VC-1"
	case strings.Contains(upper, "MPEG-2"):
		return "MPEG-2"
	default:
		return ""
	}
}

func extractVideoFormatFromTitle(title string) string {
	upper := strings.ToUpper(title)
	switch {
	case strings.Contains(upper, "3D"):
		return "3D"
	case strings.Contains(upper, "HSBS"):
		return "HSBS"
	default:
		return ""
	}
}

func extractHDRFormatFromTitle(title string) string {
	trimmed := strings.TrimSpace(title)
	if trimmed == "" {
		return ""
	}

	matches := findHDRTitleTokens(trimmed)
	if len(matches) == 0 {
		return ""
	}

	hasDoVi := false
	hasHDR10Plus := false
	hasHDR := false
	hasHLG := false
	hasVivid := false
	hasSDR := false
	hasEDR := false
	for _, item := range matches {
		switch strings.ToUpper(strings.TrimSpace(item)) {
		case "DOLBY VISION", "DOVI", "DV":
			hasDoVi = true
		case "HDR10+":
			hasHDR10Plus = true
		case "HDR10", "HDR":
			hasHDR = true
		case "HLG":
			hasHLG = true
		case "HDRVIVID", "VIVID":
			hasVivid = true
		case "SDR":
			hasSDR = true
		case "EDR":
			hasEDR = true
		}
	}

	switch {
	case hasDoVi && hasHDR10Plus:
		return "DoVi HDR10+"
	case hasDoVi && hasHDR:
		return "DoVi HDR"
	case hasDoVi:
		return "DoVi"
	case hasHDR10Plus:
		return "HDR10+"
	case hasVivid:
		return "HDR Vivid"
	case hasHDR:
		return "HDR"
	case hasHLG:
		return "HLG"
	case hasSDR:
		return "SDR"
	case hasEDR:
		return "EDR"
	default:
		return ""
	}
}

func hdrCleanupTags(hdr string) []string {
	trimmed := strings.TrimSpace(hdr)
	if trimmed == "" {
		return nil
	}

	seen := make(map[string]struct{}, 8)
	out := make([]string, 0, 8)
	appendTag := func(tag string) {
		tag = strings.TrimSpace(tag)
		if tag == "" {
			return
		}
		key := strings.ToUpper(tag)
		if _, ok := seen[key]; ok {
			return
		}
		seen[key] = struct{}{}
		out = append(out, tag)
	}

	appendTag(trimmed)
	for _, alias := range hdrCleanupAliases(trimmed) {
		appendTag(alias)
	}
	matches := findHDRTitleTokens(trimmed)
	for _, item := range matches {
		appendTag(item)
	}

	return out
}

func hdrCleanupAliases(hdr string) []string {
	upper := strings.ToUpper(strings.TrimSpace(hdr))
	if upper == "" {
		return nil
	}

	aliases := make([]string, 0, 6)
	switch {
	case strings.Contains(upper, "DOVI") && strings.Contains(upper, "HDR10+"):
		aliases = append(aliases, "DoVi", "DV", "Dolby Vision", "HDR10+", "HDR")
	case strings.Contains(upper, "DOVI") && strings.Contains(upper, "HDR"):
		aliases = append(aliases, "DoVi", "DV", "Dolby Vision", "HDR10", "HDR")
	case strings.Contains(upper, "DOVI"):
		aliases = append(aliases, "DoVi", "DV", "Dolby Vision")
	case strings.Contains(upper, "HDR10+"):
		aliases = append(aliases, "HDR10+", "HDR")
	case strings.Contains(upper, "VIVID"):
		aliases = append(aliases, "HDRVivid", "Vivid")
	case strings.Contains(upper, "HDR"):
		aliases = append(aliases, "HDR10", "HDR")
	case strings.Contains(upper, "HLG"):
		aliases = append(aliases, "HLG")
	case strings.Contains(upper, "SDR"):
		aliases = append(aliases, "SDR")
	case strings.Contains(upper, "EDR"):
		aliases = append(aliases, "EDR")
	}
	return aliases
}

func findHDRTitleTokens(text string) []string {
	indexes := reHDRTitleToken.FindAllStringIndex(text, -1)
	if len(indexes) == 0 {
		return nil
	}

	matches := make([]string, 0, len(indexes))
	for _, loc := range indexes {
		if len(loc) < 2 {
			continue
		}
		start, end := loc[0], loc[1]
		if !isHDRTitleTokenBoundary(text, start, end) {
			continue
		}
		value := strings.TrimSpace(text[start:end])
		if value == "" {
			continue
		}
		matches = append(matches, value)
	}
	return matches
}

func isHDRTitleTokenBoundary(text string, start int, end int) bool {
	if start > 0 {
		prev, _ := utf8.DecodeLastRuneInString(text[:start])
		if isHDRTitleWordRune(prev) {
			return false
		}
	}
	if end < len(text) {
		next, _ := utf8.DecodeRuneInString(text[end:])
		if isHDRTitleWordRune(next) {
			return false
		}
	}
	return true
}

func isHDRTitleWordRune(r rune) bool {
	return r == '_' || unicode.IsLetter(r) || unicode.IsDigit(r)
}

func extractBitDepthFromTitle(title string) string {
	re := regexp.MustCompile(`(?i)\b(8|10|12|16|24)\s*BIT\b`)
	match := re.FindStringSubmatch(title)
	if len(match) >= 2 {
		return match[1] + "bit"
	}
	return ""
}

func extractFrameRateFromTitle(title string) string {
	re := regexp.MustCompile(`(?i)\b(\d{2,3}(?:\.\d+)?)\s*FPS\b`)
	match := re.FindStringSubmatch(title)
	if len(match) >= 2 {
		return strings.TrimSpace(match[1]) + "fps"
	}
	return ""
}

// normalizeTitleVideoCodecTokens 对齐 Python：修复视频编码 token 中缺少点号的情况。
// 典型场景：H264 -> H.264、H 264 -> H.264、H265 -> H.265、H 265 -> H.265。
var (
	reVideoCodecH265 = regexp.MustCompile(`(?i)\bH\s*[\s.]?\s*265\b`)
	reVideoCodecH264 = regexp.MustCompile(`(?i)\bH\s*[\s.]?\s*264\b`)
)

func normalizeTitleVideoCodecTokens(title string) string {
	trimmed := strings.TrimSpace(title)
	if trimmed == "" {
		return title
	}
	out := reVideoCodecH265.ReplaceAllString(trimmed, "H.265")
	out = reVideoCodecH264.ReplaceAllString(out, "H.264")
	return out
}

func normalizeTitleAudioTokens(title string) string {
	trimmed := strings.TrimSpace(title)
	if trimmed == "" {
		return title
	}

	out := trimmed
	out = strings.ReplaceAll(out, "。", ".")
	out = strings.ReplaceAll(out, "．", ".")

	// 对齐 Python：先做 codec token 的文本标准化，再修复声道/Atmos/音轨数的缺空格问题。
	// 典型场景：DTS-HDMA 2.0（缺少 DTS-HD 与 MA 之间空格）会导致音频编码被误判为 DTS 2.0，剩余 -HDMA 无法识别。
	codecStandardizationRules := []struct {
		pattern     *regexp.Regexp
		replacement string
	}{
		{regexp.MustCompile(`(?i)\bDTS[-\s\.]*HD[-\s\.]*MA\b`), "DTS-HD MA"},
		{regexp.MustCompile(`(?i)\bDTS[-\s\.]*HD[-\s\.]*HR\b`), "DTS-HD HR"},
		{regexp.MustCompile(`(?i)\bTrue[-\s\.]*HD\b`), "TrueHD"},
		{regexp.MustCompile(`(?i)\bDTS[-\s\.]*X\b`), "DTS:X"},
		{regexp.MustCompile(`(?i)\bDTS\s*X\b`), "DTS:X"},
		{regexp.MustCompile(`(?i)\bE[-\s\.]*AC[-\s\.]*3\b`), "DDP"},
		// 对齐 Python：DD+ 等价于 DDP（E-AC-3），这里统一输出 DDP，且兼容全角加号等变体。
		{regexp.MustCompile(`(?i)(^|[^\p{L}\p{N}_])DD\s*[\+＋﹢]([^\p{L}\p{N}_]|$)`), "${1}DDP${2}"},
		{regexp.MustCompile(`(?i)\bAC[-\s\.]*3\b`), "DD"},
		{regexp.MustCompile(`(?i)\bLPCM\s*/\s*PCM\b`), "LPCM"},
	}
	for _, rule := range codecStandardizationRules {
		out = rule.pattern.ReplaceAllString(out, rule.replacement)
	}

	// 对齐 Python：修复音频标签中常见的缺空格/缺小数点/单复数问题（避免影响其他字段提取）。
	audioKeywords := `DTS[-\s\.]*HD[-\s\.]*MA|DTS[-\s\.]*HD[-\s\.]*HR|DTS[-\s\.]*HD|DTS[:\-\s\.]*X|DTS|TRUEHD|DDP|DD\+|DD|E[-\s]?AC[-\s]?3|AC[-\s]?3|AC3|FLAC|AAC|LPCM|PCM|OPUS|MP3`

	// 修复 "DDP 5 1" -> "DDP 5.1" 这类空格分隔声道格式。
	reSpaceDecimal := regexp.MustCompile(`(?i)\b(` + audioKeywords + `)\b\s*(\d)\s*(\d)\b`)
	out = reSpaceDecimal.ReplaceAllString(out, `$1 $2.$3`)

	// 修复 "FLAC5.1" / "TrueHD7.1.4" -> "FLAC 5.1" / "TrueHD 7.1.4" 这类缺空格粘连。
	reGlueChannel := regexp.MustCompile(`(?i)\b(` + audioKeywords + `)(\d{1,2}(?:\.\d)+)\b`)
	out = reGlueChannel.ReplaceAllString(out, `$1 $2`)

	// 修复 "Atmos7.1" / "X7.1.4" -> "Atmos 7.1" / "X 7.1.4"。
	reAtmosGlue := regexp.MustCompile(`(?i)\b(Atmos|X)(\d{1,2}(?:\.\d)+)\b`)
	out = reAtmosGlue.ReplaceAllString(out, `$1 $2`)

	// 修复 "3Audio" -> "3Audios"。
	reAudioCountSingular := regexp.MustCompile(`(?i)\b(\d+)Audio\b`)
	out = reAudioCountSingular.ReplaceAllString(out, `$1Audios`)

	out = strings.Join(strings.Fields(out), " ")
	return strings.TrimSpace(out)
}

func extractAudioFromTitle(title string) string {
	upper := strings.ToUpper(title)
	audioCodec := ""
	audioCodecPos := -1
	switch {
	case strings.Contains(upper, "TRUEHD"):
		audioCodec = "TrueHD"
		audioCodecPos = strings.Index(upper, "TRUEHD")
	case strings.Contains(upper, "DTS:X"), strings.Contains(upper, "DTS X"):
		audioCodec = "DTS:X"
		if idx := strings.Index(upper, "DTS:X"); idx >= 0 {
			audioCodecPos = idx
		} else {
			audioCodecPos = strings.Index(upper, "DTS X")
		}
	case strings.Contains(upper, "DTS-HD MA"), strings.Contains(upper, "DTS HD MA"):
		audioCodec = "DTS-HD MA"
		if idx := strings.Index(upper, "DTS-HD MA"); idx >= 0 {
			audioCodecPos = idx
		} else {
			audioCodecPos = strings.Index(upper, "DTS HD MA")
		}
	case strings.Contains(upper, "DTS-HD HR"), strings.Contains(upper, "DTS HD HR"):
		audioCodec = "DTS-HD HR"
		if idx := strings.Index(upper, "DTS-HD HR"); idx >= 0 {
			audioCodecPos = idx
		} else {
			audioCodecPos = strings.Index(upper, "DTS HD HR")
		}
	case strings.Contains(upper, "DTS"):
		audioCodec = "DTS"
		audioCodecPos = strings.Index(upper, "DTS")
	case strings.Contains(upper, "E-AC-3"), strings.Contains(upper, "DDP"), strings.Contains(upper, "DD+"), strings.Contains(upper, "DD＋"), strings.Contains(upper, "DD﹢"):
		audioCodec = "DDP"
		// 查找 DDP 或 DD+ 的位置
		if idx := strings.Index(upper, "DDP"); idx >= 0 {
			audioCodecPos = idx
		} else if idx := strings.Index(upper, "DD+"); idx >= 0 {
			audioCodecPos = idx
		} else if idx := strings.Index(upper, "DD＋"); idx >= 0 {
			audioCodecPos = idx
		} else if idx := strings.Index(upper, "DD﹢"); idx >= 0 {
			audioCodecPos = idx
		} else if idx := strings.Index(upper, "E-AC-3"); idx >= 0 {
			audioCodecPos = idx
		}
	case reAudioCodecDD.MatchString(title), strings.Contains(upper, "AC-3"), strings.Contains(upper, "AC3"):
		audioCodec = "DD"
		if idx := reAudioCodecDD.FindStringIndex(title); idx != nil {
			audioCodecPos = idx[0]
		} else if idx := strings.Index(upper, "AC-3"); idx >= 0 {
			audioCodecPos = idx
		} else {
			audioCodecPos = strings.Index(upper, "AC3")
		}
	case strings.Contains(upper, "FLAC"):
		audioCodec = "FLAC"
		audioCodecPos = strings.Index(upper, "FLAC")
	case strings.Contains(upper, "AAC"):
		audioCodec = "AAC"
		audioCodecPos = strings.Index(upper, "AAC")
	case strings.Contains(upper, "AV3A"):
		audioCodec = "AV3A"
		audioCodecPos = strings.Index(upper, "AV3A")
	case strings.Contains(upper, "ALAC"):
		audioCodec = "ALAC"
		audioCodecPos = strings.Index(upper, "ALAC")
	case strings.Contains(upper, "APE"):
		audioCodec = "APE"
		audioCodecPos = strings.Index(upper, "APE")
	case strings.Contains(upper, "WAV"):
		audioCodec = "WAV"
		audioCodecPos = strings.Index(upper, "WAV")
	case strings.Contains(upper, "OGG"):
		audioCodec = "OGG"
		audioCodecPos = strings.Index(upper, "OGG")
	case strings.Contains(upper, "DSD"):
		audioCodec = "DSD"
		audioCodecPos = strings.Index(upper, "DSD")
	case strings.Contains(upper, "LPCM"), strings.Contains(upper, "PCM"):
		audioCodec = "LPCM"
		if idx := strings.Index(upper, "LPCM"); idx >= 0 {
			audioCodecPos = idx
		} else {
			audioCodecPos = strings.Index(upper, "PCM")
		}
	case strings.Contains(upper, "OPUS"):
		audioCodec = "Opus"
		audioCodecPos = strings.Index(upper, "OPUS")
	case strings.Contains(upper, "MP3"):
		audioCodec = "MP3"
		audioCodecPos = strings.Index(upper, "MP3")
	case strings.Contains(upper, "MP2"):
		audioCodec = "MP3"
		audioCodecPos = strings.Index(upper, "MP2")
	case strings.Contains(upper, "DUAL"):
		audioCodec = "Dual"
		audioCodecPos = strings.Index(upper, "DUAL")
	}
	if audioCodec == "" {
		return ""
	}

	parts := []string{audioCodec}
	channelRe := regexp.MustCompile(`(?i)\b(\d{1,2}\.\d(?:\.\d+)?)\b`)
	// 在音频编码之后搜索声道信息，避免误匹配标题中的版本号（如 "M3GAN 2.0"）
	searchStart := 0
	if audioCodecPos >= 0 {
		searchStart = audioCodecPos + len(audioCodec)
	}
	if searchStart < len(title) {
		channelMatch := channelRe.FindStringSubmatch(title[searchStart:])
		if len(channelMatch) >= 2 {
			parts = append(parts, channelMatch[1])
		}
	}
	if strings.Contains(upper, "ATMOS") {
		parts = append(parts, "Atmos")
	}
	audioCountRe := regexp.MustCompile(`(?i)\b(\d+\s*Audios?)\b`)
	if audioCountMatch := audioCountRe.FindStringSubmatch(title); len(audioCountMatch) >= 2 {
		parts = append(parts, strings.ReplaceAll(audioCountMatch[1], " ", ""))
	}
	return strings.Join(parts, " ")
}

func buildOrderedTitleComponents(values map[string]string) []map[string]any {
	result := make([]map[string]any, 0, len(defaultTitleComponentKeys)+4)
	used := map[string]struct{}{}
	for _, key := range defaultTitleComponentKeys {
		result = append(result, map[string]any{
			"key":   key,
			"value": strings.TrimSpace(values[key]),
		})
		used[key] = struct{}{}
	}

	extras := make([]string, 0)
	for key := range values {
		key = strings.TrimSpace(key)
		if key == "" {
			continue
		}
		if _, exists := used[key]; exists {
			continue
		}
		extras = append(extras, key)
	}
	sort.Strings(extras)
	for _, key := range extras {
		result = append(result, map[string]any{
			"key":   key,
			"value": strings.TrimSpace(values[key]),
		})
	}
	return result
}

// CompleteTitleComponents 补齐标题组件缺失值（主标题/制作组），并保证输出顺序稳定。
// 参数/返回：raw 为任意来源的 title_components；fallbackTitle 用于兜底拆解。
// 失败场景：raw 不合法时自动跳过坏数据并返回可用组件。
// 副作用：无。
func CompleteTitleComponents(raw []any, fallbackTitle string) []any {
	values := map[string]string{}
	for _, item := range raw {
		component, ok := item.(map[string]any)
		if !ok {
			continue
		}
		key := strings.TrimSpace(toStringSimple(component["key"], ""))
		if key == "" {
			continue
		}
		values[key] = strings.TrimSpace(toStringSimple(component["value"], ""))
	}

	mainTitle, team := splitTitleAndTeam(strings.TrimSpace(fallbackTitle), "")
	if strings.TrimSpace(values["主标题"]) == "" && mainTitle != "" {
		values["主标题"] = mainTitle
	}
	if strings.TrimSpace(values["制作组"]) == "" && team != "" {
		values["制作组"] = team
	}

	return MapTitleComponentsToAny(buildOrderedTitleComponents(values))
}

// MapTitleComponentsToAny 将 map 结构组件切片转成 []any，便于写入统一参数结构。
// 参数/返回：items 为结构化组件；返回同顺序的 []any。
// 失败场景：空输入返回空切片。
// 副作用：无。
func MapTitleComponentsToAny(items []map[string]any) []any {
	if len(items) == 0 {
		return []any{}
	}
	result := make([]any, 0, len(items))
	for _, item := range items {
		result = append(result, item)
	}
	return result
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func toStringSimple(value any, fallback string) string {
	if value == nil {
		return fallback
	}
	switch typed := value.(type) {
	case string:
		if strings.TrimSpace(typed) == "" {
			return fallback
		}
		return typed
	case fmt.Stringer:
		text := strings.TrimSpace(typed.String())
		if text == "" {
			return fallback
		}
		return text
	case []byte:
		text := strings.TrimSpace(string(typed))
		if text == "" {
			return fallback
		}
		return text
	case float64:
		if typed == float64(int64(typed)) {
			return fmt.Sprintf("%d", int64(typed))
		}
		return fmt.Sprintf("%v", typed)
	default:
		text := strings.TrimSpace(fmt.Sprintf("%v", value))
		if text == "" || text == "<nil>" {
			return fallback
		}
		return text
	}
}
