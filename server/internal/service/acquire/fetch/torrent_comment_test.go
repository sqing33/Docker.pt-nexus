package fetch

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestRewriteTorrentCommentPreservesInfoHash 用真实 .torrent 文件验证：
// 1) 重写 comment 后 infohash 不变（info 字节原样保留）；
// 2) comment 字段被正确写入新值；
// 3) 重写后的字节仍是合法 bencode（可被解析）。
func TestRewriteTorrentCommentPreservesInfoHash(t *testing.T) {
	dir := filepath.Join("..", "..", "..", "..", "data", "tmp", "torrents")
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Skipf("跳过：找不到种子样本目录 %s: %v", dir, err)
	}
	sample := ""
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".torrent") {
			sample = filepath.Join(dir, e.Name())
			break
		}
	}
	if sample == "" {
		t.Skip("跳过：样本目录无 .torrent 文件")
	}

	original, err := os.ReadFile(sample)
	if err != nil {
		t.Fatalf("读取样本失败: %v", err)
	}
	origMeta, err := ParseTorrentContentMeta(original)
	if err != nil {
		t.Fatalf("解析原始种子失败: %v", err)
	}
	origInfoHash := origMeta.Meta.InfoHash
	t.Logf("原始 infohash=%s name=%s", origInfoHash, origMeta.Meta.Name)

	detailURL := "https://example.org/details.php?id=12345"
	rewritten, err := RewriteTorrentComment(original, detailURL)
	if err != nil {
		t.Fatalf("RewriteTorrentComment 失败: %v", err)
	}

	// 1) infohash 不变
	newMeta, err := ParseTorrentContentMeta(rewritten)
	if err != nil {
		t.Fatalf("重写后解析失败（字节可能非法）: %v", err)
	}
	if newMeta.Meta.InfoHash != origInfoHash {
		t.Fatalf("infohash 变化！原=%s 新=%s", origInfoHash, newMeta.Meta.InfoHash)
	}
	t.Logf("重写后 infohash=%s（保持不变）✓", newMeta.Meta.InfoHash)

	// 2) comment 字段被写入新值
	gotComment := extractTopLevelComment(rewritten)
	if gotComment != detailURL {
		t.Fatalf("comment 写入不符 期望=%s 实际=%s", detailURL, gotComment)
	}
	t.Logf("comment 已写入 ✓: %s", gotComment)

	// 3) 再次重写（已有 comment）替换为新值，infohash 仍不变
	detailURL2 := "https://example.org/details.php?id=99999"
	rewritten2, err := RewriteTorrentComment(rewritten, detailURL2)
	if err != nil {
		t.Fatalf("二次重写失败: %v", err)
	}
	newMeta2, _ := ParseTorrentContentMeta(rewritten2)
	if newMeta2.Meta.InfoHash != origInfoHash {
		t.Fatalf("二次重写 infohash 变化！原=%s 新=%s", origInfoHash, newMeta2.Meta.InfoHash)
	}
	if got := extractTopLevelComment(rewritten2); got != detailURL2 {
		t.Fatalf("二次重写 comment 不符 期望=%s 实际=%s", detailURL2, got)
	}
	t.Logf("二次重写 comment 已替换 ✓: %s", extractTopLevelComment(rewritten2))

	// 4) 空值保留原 comment
	rewritten3, err := RewriteTorrentComment(rewritten2, "")
	if err != nil {
		t.Fatalf("空值重写失败: %v", err)
	}
	if got := extractTopLevelComment(rewritten3); got != detailURL2 {
		t.Fatalf("空值应保留原 comment 期望=%s 实际=%s", detailURL2, got)
	}
	t.Logf("空值保留原 comment ✓")
}

// extractTopLevelComment 解析 .torrent 顶级 comment 字段值（测试辅助）。
func extractTopLevelComment(content []byte) string {
	p := &bdecodeParser{data: content}
	if err := p.expect('d'); err != nil {
		return ""
	}
	for p.idx < len(p.data) && p.data[p.idx] != 'e' {
		keyBytes, err := p.parseBytes()
		if err != nil {
			return ""
		}
		key := string(keyBytes)
		if key == "comment" {
			val, err := p.parseValue()
			if err != nil {
				return ""
			}
			if b, ok := val.([]byte); ok {
				return string(b)
			}
			return ""
		}
		if _, err := p.parseValue(); err != nil {
			return ""
		}
	}
	return ""
}
