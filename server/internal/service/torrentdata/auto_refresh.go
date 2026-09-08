package torrentdata

import (
	"time"

	"github.com/pt-nexus/server/internal/platform/logx"
)

const (
	autoRefreshLogModule          = "定时刷新种子"
	autoRefreshMinIntervalMinutes = 5
	autoRefreshDefaultMinutes     = 30
)

// StartAutoRefresh 启动后台定时刷新种子信息任务。
// 复用 RefreshData（即 api/refresh_data 接口）逻辑，按配置间隔周期调用。
// 失败场景：s 为空时直接返回。
// 副作用：启动后台 goroutine，重复调用幂等。
func (s *TorrentDataService) StartAutoRefresh() {
	if s == nil {
		return
	}
	s.refreshOnce.Do(func() {
		go s.runAutoRefresh()
		logx.Infof(autoRefreshLogModule, "定时刷新种子调度器已启动")
	})
}

// StopAutoRefresh 停止后台定时刷新任务，等待 goroutine 退出。
func (s *TorrentDataService) StopAutoRefresh() {
	if s == nil {
		return
	}
	select {
	case <-s.refreshStopCh:
	default:
		close(s.refreshStopCh)
		<-s.refreshDoneCh
	}
}

func (s *TorrentDataService) runAutoRefresh() {
	defer close(s.refreshDoneCh)

	intervalMinutes := s.resolveRefreshIntervalMinutes()
	ticker := time.NewTicker(time.Duration(intervalMinutes) * time.Minute)
	defer ticker.Stop()

	for {
		select {
		case <-s.refreshStopCh:
			logx.Infof(autoRefreshLogModule, "定时刷新种子调度器已停止")
			return
		case <-ticker.C:
			current := s.resolveRefreshIntervalMinutes()
			if current != intervalMinutes {
				intervalMinutes = current
				ticker.Reset(time.Duration(intervalMinutes) * time.Minute)
				logx.Infof(autoRefreshLogModule, "刷新间隔已更新 interval=%dm", intervalMinutes)
			}
			if !s.autoRefreshEnabled() {
				continue
			}
			s.RefreshData()
		}
	}
}

// resolveRefreshIntervalMinutes 从配置读取刷新间隔（分钟），低于最小值则钳制。
func (s *TorrentDataService) resolveRefreshIntervalMinutes() int {
	if s == nil || s.cfg == nil {
		return autoRefreshDefaultMinutes
	}
	settings := s.cfg.Get()
	minutes := intValue(settings["torrent_refresh_interval_minutes"], autoRefreshDefaultMinutes)
	if minutes < autoRefreshMinIntervalMinutes {
		return autoRefreshMinIntervalMinutes
	}
	return minutes
}

// autoRefreshEnabled 从配置读取是否启用定时刷新，缺省视为开启。
func (s *TorrentDataService) autoRefreshEnabled() bool {
	if s == nil || s.cfg == nil {
		return true
	}
	settings := s.cfg.Get()
	return toBool(settings["torrent_refresh_enabled"], true)
}
