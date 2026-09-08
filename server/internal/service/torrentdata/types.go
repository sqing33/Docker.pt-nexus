package torrentdata

import (
	"sync"
	"sync/atomic"

	"github.com/pt-nexus/server/internal/config"
	"github.com/pt-nexus/server/internal/repository"
)

type TorrentsDataParams struct {
	Page                      int
	PageSize                  int
	PathFilters               []string
	StateFilters              []string
	SourceDataStatusFilters   []string
	DownloaderFilters         []string
	SourceAvailabilityFilters []string
	ExistSiteNames            []string
	NotExistSiteNames         []string
	NameSearch                string
	SortProp                  string
	SortOrder                 string
	ExcludeExisting           bool
	OnlyCompleted             bool
}

type siteSummary struct {
	Uploaded  int64
	Comment   *string
	Migration int
	State     string
	Seeders   int64
}

type torrentSummary struct {
	Hash          string
	Hashes        []string
	Name          string
	SavePath      string
	Size          int64
	Progress      float64
	StateSet      map[string]struct{}
	Sites         map[string]*siteSummary
	TotalUploaded int64
	Seeders       int64
	DownloaderIDs []string
	OfficialSite  string
}

type TorrentDataService struct {
	repo      *repository.TorrentDataRepository
	cfg       *config.Manager
	iyuuTasks *IYUUTaskService

	refreshMu      sync.Mutex
	refreshRunning bool

	refreshStopCh chan struct{}
	refreshDoneCh chan struct{}
	refreshOnce   sync.Once

	iyuuMu      sync.Mutex
	iyuuRunning atomic.Bool

	iyuuLog func(level string, message string)
}

func NewTorrentDataService(repo *repository.TorrentDataRepository, cfg *config.Manager) *TorrentDataService {
	return &TorrentDataService{
		repo:          repo,
		cfg:           cfg,
		iyuuTasks:     NewIYUUTaskService(),
		refreshStopCh: make(chan struct{}),
		refreshDoneCh: make(chan struct{}),
	}
}

// SetIYUULogger 设置 IYUU 查询过程的日志回调，便于在设置页展示进度信息。
// 参数/返回：level 为 INFO/WARN/ERROR 等等级，message 为完整日志文本；无返回值。
// 失败场景：无。
// 副作用：将日志写入回调实现方（通常为 SettingsService 的内存日志队列）。
func (s *TorrentDataService) SetIYUULogger(logger func(level string, message string)) {
	s.iyuuMu.Lock()
	s.iyuuLog = logger
	s.iyuuMu.Unlock()
}
