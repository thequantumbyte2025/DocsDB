package handlers

import (
    "encoding/json"
    "net/http"
    "strconv"

    "github.com/gorilla/mux"
    "go-docs-backend/db"
    "go-docs-backend/models"
)

func CreateDocument(w http.ResponseWriter, r *http.Request) {
    var doc models.Document
    if err := json.NewDecoder(r.Body).Decode(&doc); err != nil {
        http.Error(w, "Datos inválidos", http.StatusBadRequest)
        return
    }

    if result := db.DB.Create(&doc); result.Error != nil {
        http.Error(w, "Error al guardar", http.StatusInternalServerError)
        return
    }

    w.WriteHeader(http.StatusCreated)
    json.NewEncoder(w).Encode(doc)
}

func GetAllDocuments(w http.ResponseWriter, r *http.Request) {
    var docs []models.Document
    if err := db.DB.Find(&docs).Error; err != nil {
        http.Error(w, "Error al obtener documentos", http.StatusInternalServerError)
        return
    }
    json.NewEncoder(w).Encode(docs)
}

func GetDocumentByID(w http.ResponseWriter, r *http.Request) {
    id := mux.Vars(r)["id"]
    var doc models.Document
    if err := db.DB.First(&doc, id).Error; err != nil {
        http.Error(w, "Documento no encontrado", http.StatusNotFound)
        return
    }
    json.NewEncoder(w).Encode(doc)
}

func UpdateDocument(w http.ResponseWriter, r *http.Request) {
    id := mux.Vars(r)["id"]
    var doc models.Document
    if err := db.DB.First(&doc, id).Error; err != nil {
        http.Error(w, "Documento no encontrado", http.StatusNotFound)
        return
    }

    var updated models.Document
    if err := json.NewDecoder(r.Body).Decode(&updated); err != nil {
        http.Error(w, "Datos inválidos", http.StatusBadRequest)
        return
    }

    db.DB.Model(&doc).Updates(updated)
    json.NewEncoder(w).Encode(doc)
}

func DeleteDocument(w http.ResponseWriter, r *http.Request) {
    id := mux.Vars(r)["id"]
    var doc models.Document
    if err := db.DB.Delete(&doc, id).Error; err != nil {
        http.Error(w, "Error al eliminar", http.StatusInternalServerError)
        return
    }
    w.WriteHeader(http.StatusNoContent)
}
