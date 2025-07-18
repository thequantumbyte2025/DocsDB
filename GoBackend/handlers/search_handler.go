package handlers

import (
    "net/http"
    "strings"
    "go-docs-backend/db"
    "go-docs-backend/models"
    "encoding/json"
)

func SearchByKeyword(w http.ResponseWriter, r *http.Request) {
    term := strings.TrimSpace(r.URL.Query().Get("term"))
    if term == "" {
        http.Error(w, "Término de búsqueda requerido", http.StatusBadRequest)
        return
    }
    
    var docs []models.Document
    if err := db.DB.Where("? = ANY (keywords)", term).Find(&docs).Error; err != nil {
        http.Error(w, "Error en la búsqueda", http.StatusInternalServerError)
        return
    }
    json.NewEncoder(w).Encode(docs)
}

func SearchByTitle(w http.ResponseWriter, r *http.Request) {
    term := strings.TrimSpace(r.URL.Query().Get("term"))
    if term == "" {
        http.Error(w, "Término de búsqueda requerido", http.StatusBadRequest)
        return
    }
    
    var docs []models.Document
    if err := db.DB.Where("LOWER(title) LIKE LOWER(?)", "%"+term+"%").Find(&docs).Error; err != nil {
        http.Error(w, "Error en la búsqueda", http.StatusInternalServerError)
        return
    }
    json.NewEncoder(w).Encode(docs)
}

func SearchBySubtitle(w http.ResponseWriter, r *http.Request) {
    term := strings.TrimSpace(r.URL.Query().Get("term"))
    if term == "" {
        http.Error(w, "Término de búsqueda requerido", http.StatusBadRequest)
        return
    }
    
    var docs []models.Document
    if err := db.DB.Where("LOWER(subtitle) LIKE LOWER(?)", "%"+term+"%").Find(&docs).Error; err != nil {
        http.Error(w, "Error en la búsqueda", http.StatusInternalServerError)
        return
    }
    json.NewEncoder(w).Encode(docs)
}
