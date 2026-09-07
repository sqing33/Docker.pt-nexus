package repository

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/glebarez/sqlite"
	"github.com/pt-nexus/server/internal/config"
	"gorm.io/driver/mysql"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

type Store struct {
	DB     *gorm.DB
	DBType string
}

func NewStore(paths config.RuntimePaths) (*Store, error) {
	dbType := strings.ToLower(strings.TrimSpace(os.Getenv("DB_TYPE")))
	desktopCfg := config.DatabaseConfig{}
	if dbType == "" {
		loadedCfg, found, loadErr := config.LoadDesktopDatabaseConfig(paths)
		if loadErr != nil {
			return nil, loadErr
		}
		if found {
			desktopCfg = loadedCfg
			if loadedCfg.Type != "" {
				dbType = loadedCfg.Type
			}
		}
	}
	if dbType == "" {
		dbType = "sqlite"
	}

	var (
		db  *gorm.DB
		err error
	)

	switch dbType {
	case "mysql":
		host := firstNonEmpty(os.Getenv("MYSQL_HOST"), desktopCfg.MySQL.Host)
		user := firstNonEmpty(os.Getenv("MYSQL_USER"), desktopCfg.MySQL.User)
		password := firstNonEmpty(os.Getenv("MYSQL_PASSWORD"), desktopCfg.MySQL.Password)
		database := firstNonEmpty(os.Getenv("MYSQL_DATABASE"), desktopCfg.MySQL.Database)
		port := firstNonEmpty(os.Getenv("MYSQL_PORT"), intToString(desktopCfg.MySQL.Port), "3306")
		dsn := fmt.Sprintf("%s:%s@tcp(%s:%s)/%s?charset=utf8mb4&parseTime=True&loc=Local", user, password, host, port, database)
		db, err = gorm.Open(mysql.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	case "postgresql":
		host := firstNonEmpty(os.Getenv("POSTGRES_HOST"), desktopCfg.PostgreSQL.Host)
		user := firstNonEmpty(os.Getenv("POSTGRES_USER"), desktopCfg.PostgreSQL.User)
		password := firstNonEmpty(os.Getenv("POSTGRES_PASSWORD"), desktopCfg.PostgreSQL.Password)
		database := firstNonEmpty(os.Getenv("POSTGRES_DATABASE"), desktopCfg.PostgreSQL.Database)
		port := firstNonEmpty(os.Getenv("POSTGRES_PORT"), intToString(desktopCfg.PostgreSQL.Port), "5432")
		sslMode := firstNonEmpty(os.Getenv("POSTGRES_SSLMODE"), desktopCfg.PostgreSQL.SSLMode, "disable")
		dsn := fmt.Sprintf("host=%s user=%s password=%s dbname=%s port=%s sslmode=%s TimeZone=Asia/Shanghai", host, user, password, database, port, sslMode)
		db, err = gorm.Open(postgres.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	case "sqlite":
		fallthrough
	default:
		dbType = "sqlite"
		dbPath := filepath.Join(paths.DataDir, "pt_stats.db")
		if value := strings.TrimSpace(os.Getenv("SQLITE_PATH")); value != "" {
			dbPath = value
		} else if value := strings.TrimSpace(desktopCfg.SQLitePath); value != "" {
			dbPath = value
		}
		// SQLite DSN：开启 WAL 模式（读写不互斥）+ busy_timeout 5s（锁冲突时等待而非立即失败）+ synchronous=NORMAL（WAL 下安全且更快）
		dsn := dbPath + "?_pragma=journal_mode(WAL)&_pragma=busy_timeout(5000)&_pragma=synchronous(NORMAL)"
		db, err = gorm.Open(sqlite.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	}

	if err != nil {
		return nil, fmt.Errorf("open database failed: %w", err)
	}

	sqlDB, err := db.DB()
	if err != nil {
		return nil, fmt.Errorf("get sql.DB failed: %w", err)
	}
	if dbType == "sqlite" {
		// SQLite 只支持单写入者，MaxOpenConns=1 序列化所有 DB 访问，
		// 避免连接池复用已在事务中的连接导致 "cannot start a transaction within a transaction"
		sqlDB.SetMaxOpenConns(1)
		sqlDB.SetMaxIdleConns(1)
	} else {
		sqlDB.SetMaxOpenConns(20)
		sqlDB.SetMaxIdleConns(10)
	}

	return &Store{DB: db, DBType: dbType}, nil
}

func (s *Store) GroupColumn() string {
	if s.DBType == "postgresql" {
		return `"group"`
	}
	return "`group`"
}

func getEnvOrDefault(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		trimmed := strings.TrimSpace(value)
		if trimmed != "" {
			return trimmed
		}
	}
	return ""
}

func intToString(value int) string {
	if value <= 0 {
		return ""
	}
	return fmt.Sprintf("%d", value)
}
