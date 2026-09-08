package fetch

import (
	"bytes"
	"errors"
	"fmt"
	"sort"
	"strings"
)

// RewriteTorrentComment 把 .torrent 字节中的顶级 comment 字段替换为 comment，
// 保持 info 字典原始字节不变（infohash 不变），其他顶级字段原样保留，按 bencode key 字典序重组。
// 当 comment 为空串时保留原始 comment 字段（不做改动），避免破坏原种子元信息。
// 参数：content 为 .torrent 文件字节；comment 为要写入的详情页地址。
// 返回：重写后的 .torrent 字节；若 content 非法或缺少 info 返回错误。
// 副作用：无（纯字节变换，不触碰磁盘）。
func RewriteTorrentComment(content []byte, comment string) ([]byte, error) {
	if len(content) == 0 {
		return nil, errors.New("torrent 内容为空")
	}
	comment = strings.TrimSpace(comment)

	p := &bdecodeParser{data: content}
	if err := p.expect('d'); err != nil {
		return nil, fmt.Errorf("重写 comment 失败: %w", err)
	}

	type field struct {
		key      string
		valStart int
		valEnd   int
	}
	fields := make([]field, 0, 8)
	infoStart, infoEnd := -1, -1
	for p.idx < len(p.data) && p.data[p.idx] != 'e' {
		keyBytes, err := p.parseBytes()
		if err != nil {
			return nil, fmt.Errorf("重写 comment 解析 key 失败: %w", err)
		}
		key := string(keyBytes)
		valStart := p.idx
		if key == "info" {
			infoStart = valStart
		}
		if _, err := p.parseValue(); err != nil {
			return nil, fmt.Errorf("重写 comment 解析 value 失败: %w", err)
		}
		valEnd := p.idx
		if key == "info" {
			infoEnd = valEnd
		}
		fields = append(fields, field{key: key, valStart: valStart, valEnd: valEnd})
	}
	if err := p.expect('e'); err != nil {
		return nil, fmt.Errorf("重写 comment 闭合失败: %w", err)
	}
	if infoStart < 0 || infoEnd <= infoStart {
		return nil, errors.New("torrent 缺少 info 字段，无法重写 comment")
	}

	// 按 bencode 字典序（字节序）输出；info 用原始字节保证 infohash 不变；comment 用新值。
	sort.SliceStable(fields, func(i, j int) bool { return fields[i].key < fields[j].key })

	var buf bytes.Buffer
	buf.Grow(len(content) + len(comment) + 32)
	buf.WriteByte('d')

	commentWritten := false
	for _, f := range fields {
		buf.Write(encodeBencodeString(f.key))
		switch {
		case f.key == "info":
			buf.Write(content[infoStart:infoEnd])
		case f.key == "comment" && comment != "":
			commentWritten = true
			buf.Write(encodeBencodeString(comment))
		default:
			buf.Write(content[f.valStart:f.valEnd])
		}
	}
	if !commentWritten && comment != "" {
		buf.Write(encodeBencodeString("comment"))
		buf.Write(encodeBencodeString(comment))
	}
	buf.WriteByte('e')
	return buf.Bytes(), nil
}

// encodeBencodeString 返回 bencode 编码的字符串字节（长度前缀 + 内容）。
func encodeBencodeString(s string) []byte {
	return []byte(fmt.Sprintf("%d:%s", len(s), s))
}
