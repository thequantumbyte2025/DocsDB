package handlers

import (
    "encoding/json"
    "net/http"
    "os"
    "go-docs-backend/auth"
)

func LoginHandler(w http.ResponseWriter, r *http.Request) {
    var credentials struct {
        Username string `json:"username"`
        Password string `json:"password"`
    }

    if err := json.NewDecoder(r.Body).Decode(&credentials); err != nil {
        http.Error(w, "Datos inválidos", http.StatusBadRequest)
        return
    }

    // Validación usando variables de entorno
    adminUser := getEnvOrDefault("ADMIN_USER", "admin")
    adminPass := getEnvOrDefault("ADMIN_PASS", "1234")
    
    if credentials.Username != adminUser || credentials.Password != adminPass {
        http.Error(w, "Credenciales inválidas", http.StatusUnauthorized)
        return
    }

    token, err := auth.GenerateJWT(1)
    if err != nil {
        http.Error(w, "Error generando token", http.StatusInternalServerError)
        return
    }

    json.NewEncoder(w).Encode(map[string]string{"token": token})
}

func getEnvOrDefault(key, defaultValue string) string {
    if value := os.Getenv(key); value != "" {
        return value
    }
    return defaultValue
}
