package db

import (
    "fmt"
    "gorm.io/driver/postgres"
    "gorm.io/gorm"
    "log"
    "time"
    "os"
)

var DB *gorm.DB

func Connect() {
    host := getEnvOrDefault("DB_HOST", "localhost")
    user := getEnvOrDefault("DB_USER", "postgres")
    password := getEnvOrDefault("DB_PASSWORD", "tu_password")
    dbname := getEnvOrDefault("DB_NAME", "tu_db")
    port := getEnvOrDefault("DB_PORT", "5432")
    
    dsn := fmt.Sprintf("host=%s user=%s password=%s dbname=%s port=%s sslmode=disable", host, user, password, dbname, port)
    var err error
    DB, err = gorm.Open(postgres.Open(dsn), &gorm.Config{})
    if err != nil {
        log.Fatal("Error al conectar con la base de datos:", err)
    }

	sqlDB, err := DB.DB()
	if err != nil {
		log.Fatal("Error al obtener la conexión SQL:", err)
	}
    // Agregamos configuracion para pooling en la conexion para 
    // preparar alto trafico
    //
	sqlDB.SetMaxOpenConns(100)      // Número máximo de conexiones abiertas
	sqlDB.SetMaxIdleConns(25)       // Conexiones inactivas que pueden permanecer en el pool
	sqlDB.SetConnMaxLifetime(time.Hour)


}

func getEnvOrDefault(key, defaultValue string) string {
    if value := os.Getenv(key); value != "" {
        return value
    }
    return defaultValue
}
