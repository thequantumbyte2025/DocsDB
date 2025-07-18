package models

import "time"

type Document struct {
    ID        uint      `gorm:"primaryKey" json:"id"`
    Title     string    `json:"title"`
    Subtitle  string    `json:"subtitle"`
    CreatedAt time.Time `json:"created_at"`
    Content   string    `json:"content"`
    Keywords  []string  `gorm:"type:text[]" json:"keywords"`
}
