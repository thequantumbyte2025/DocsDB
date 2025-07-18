package main

import (
    "log"
    "net/http"

    "go-docs-backend/auth"
    "go-docs-backend/db"
    "go-docs-backend/handlers"
    "go-docs-backend/models"

    "github.com/gorilla/mux"
)

func main() {
    db.Connect()
    db.DB.AutoMigrate(&models.Document{})

    r := mux.NewRouter()

    // Login endpoint (no auth required)
    r.HandleFunc("/login", handlers.LoginHandler).Methods("POST")

    // Protected routes with authentication
    protected := r.PathPrefix("/").Subrouter()
    protected.Use(auth.AuthMiddleware)

    // CRUD
    protected.HandleFunc("/documents", handlers.CreateDocument).Methods("POST")
    protected.HandleFunc("/documents", handlers.GetAllDocuments).Methods("GET")
    protected.HandleFunc("/documents/{id}", handlers.GetDocumentByID).Methods("GET")
    protected.HandleFunc("/documents/{id}", handlers.UpdateDocument).Methods("PUT")
    protected.HandleFunc("/documents/{id}", handlers.DeleteDocument).Methods("DELETE")

    // Búsquedas
    protected.HandleFunc("/search/keywords", handlers.SearchByKeyword).Methods("GET")
    protected.HandleFunc("/search/title", handlers.SearchByTitle).Methods("GET")
    protected.HandleFunc("/search/subtitle", handlers.SearchBySubtitle).Methods("GET")

    log.Println("Servidor corriendo en http://localhost:8080")
    log.Fatal(http.ListenAndServe(":8080", r))
}
