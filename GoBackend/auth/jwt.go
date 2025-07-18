package auth

import (
    "errors"
    "os"
    "time"

    "github.com/golang-jwt/jwt/v5"
)

var secretKey = []byte(getEnvOrDefault("JWT_SECRET", "your-secret-key"))

type Claims struct {
    UserID uint `json:"user_id"`
    jwt.RegisteredClaims
}

func GenerateJWT(userID uint) (string, error) {
    expirationTime := time.Now().Add(24 * time.Hour)
    claims := &Claims{
        UserID: userID,
        RegisteredClaims: jwt.RegisteredClaims{
            ExpiresAt: jwt.NewNumericDate(expirationTime),
            IssuedAt:  jwt.NewNumericDate(time.Now()),
        },
    }

    token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
    return token.SignedString(secretKey)
}

func ValidateJWT(tokenString string) (*Claims, error) {
    claims := &Claims{}
    token, err := jwt.ParseWithClaims(tokenString, claims, func(token *jwt.Token) (interface{}, error) {
        return secretKey, nil
    })

    if err != nil {
        return nil, err
    }

    if !token.Valid {
        return nil, errors.New("invalid token")
    }

    return claims, nil
}

func getEnvOrDefault(key, defaultValue string) string {
    if value := os.Getenv(key); value != "" {
        return value
    }
    return defaultValue
}