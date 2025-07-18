package auth

import (
    "net/http"
    "strings"
)

func AuthMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        token := r.Header.Get("Authorization")
        if token == "" || !strings.HasPrefix(token, "Bearer ") {
            http.Error(w, "Token no provisto", http.StatusUnauthorized)
            return
        }

        token = strings.TrimPrefix(token, "Bearer ")
        _, err := ValidateJWT(token)
        if err != nil {
            http.Error(w, "Token inválido", http.StatusUnauthorized)
            return
        }

        next.ServeHTTP(w, r)
    })
}
