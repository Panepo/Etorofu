# Authentication API — Shiratsuyu Backend

This document describes the **Authentication** endpoints exposed by the Shiratsuyu backend.
These endpoints handle user authentication, token generation, and user information retrieval.

---

## Prerequisites

All authentication endpoints except the login endpoint require a valid **JWT session** — the user must be logged in first.
Include the token in every request:

```
Authorization: Bearer <jwt_token>
```

Obtain a JWT by calling `POST /auth`:

```ts
// Request
POST /auth
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "secret",
  "server": "shiratsuyu"   // optional, defaults to "shiratsuyu"
}

// Response
{
  "id": "...",
  "userDataId": "...",
  "name": "John Doe",
  "token": "<jwt_token>",
  "usergroups": [0]
}
```

---

## Endpoints

### Login User

```
POST /auth
Content-Type: application/json
```

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `email` | `string` | ✅ | User's email address |
| `password` | `string` | ✅ | User's password |
| `server` | `string` | ❌ | Target server/service name. Defaults to `"shiratsuyu"` |

Valid `server` values (from `Server` enum):

| Value | Service |
|---|---|
| `"shiratsuyu"` | Core platform |
| `"shigure"` | Driver database |
| `"murasame"` | HDI / package management |
| `"harusame"` | Certificate management |
| `"hirato"` | Project Secretary |
| `"mikura"` | Universal CAP management |

**Example request:**

```json
{
  "email": "user@example.com",
  "password": "secret",
  "server": "shiratsuyu"
}
```

**Response — `200 OK`:**

```ts
{
  id: string;
  userDataId: string;
  name: string;
  token: string;
  usergroups: number[];
}
```

**Error Responses:**

| Status | Meaning |
|---|---|
| `401 Unauthorized` | Invalid email or password |
| `404 Not Found` | User is not allowed to use the specified service |
| `400 Bad Request` | Email or password are missing |

---

### Get Current User

```
GET /auth
Authorization: Bearer <jwt_token>
```

Returns the current user information based on the JWT token. Requires one of the following roles:
- `SHIRATSUYU_MASTER` (role: 2)
- `SHIRATSUYU_MANAGER` (role: 1)
- `SHIRATSUYU_USER` (role: 0)

**Response — `200 OK`:**

```ts
{
  id: string;
  userDataId: string;
  name: string;
  token: string;
  usergroups: number[];
}
```

**Error Responses:**

| Status | Meaning |
|---|---|
| `401 Unauthorized` | Missing or invalid JWT session |
| `403 Forbidden` | User does not have required roles |
| `404 Not Found` | User information is missing in request |

---

### Get Current User by API Key

```
GET /auth/apikey
Authorization: Bearer <api_key_token>
```

Returns the current user information based on the API key token.

**Response — `200 OK`:**

```ts
{
  id: string;
  userDataId: string;
  name: string;
  token: string;
  usergroups: number[];
}
```

**Error Responses:**

| Status | Meaning |
|---|---|
| `401 Unauthorized` | Missing or invalid API key |

---

### Get User by ID

```
GET /auth/:id
Authorization: Bearer <jwt_token>
```

Returns user information for the specified user ID. Requires one of the following roles:
- `SHIRATSUYU_MASTER` (role: 2)
- `SHIRATSUYU_MANAGER` (role: 1)
- `SHIRATSUYU_USER` (role: 0)

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `id` | `string` | ✅ | User ID to retrieve |

**Response — `200 OK`:**

```ts
{
  id: string;
  userDataId: string;
  name: string;
  token: string;
  usergroups: number[];
}
```

**Error Responses:**

| Status | Meaning |
|---|---|
| `401 Unauthorized` | Missing or invalid JWT session |
| `403 Forbidden` | User does not have required roles |
| `404 Not Found` | User does not exist or does not have associated user data |

---

## TypeScript Interfaces

```ts
export interface LoginDto {
  email: string;
  password: string;
}

export interface LoginDto2 {
  email: string;
  password: string;
  server: string;
}

export interface UserDto {
  id: string;
  userDataId?: string;
  name: string;
  token?: string;
  usergroups: number[];
  hex?: string;
  shigure?: number[];
}

export interface JwtUserData {
  id: string;
  userDataId: string;
  name: string;
  usergroups: number[];
  hex: string;
  shigure: number[];
}

export enum Server {
  SHIRATSUYU = 'shiratsuyu',
  SHIGURE = 'shigure',
  MURASAME = 'murasame',
  YUDACHI = 'yudachi',
  HARUSAME = 'harusame',
  HIRATO = 'hirato',
  MIKURA = 'mikura',
}

export enum Role {
  // api server
  SHIRATSUYU_USER = 0,
  SHIRATSUYU_MANAGER = 1,
  SHIRATSUYU_MASTER = 2,

  // gdms
  SHIGURE_USER = 10,
  SHIGURE_MANAGER = 11,
  SHIGURE_MASTER = 12,

  // hdi
  MURASAME_USER = 20,
  MURASAME_MANAGER = 21,
  MURASAME_MASTER = 22,

  // gsd
  YUDACHI_USER = 30,
  YUDACHI_MANAGER = 31,
  YUDACHI_MASTER = 32,

  // future
  HARUSAME_USER = 40,
  HARUSAME_MANAGER = 41,
  HARUSAME_MASTER = 42,
  HARUSAME_VIEWER = 43,
}
```

---

## Authentication Flow

1. **Login**: User calls `POST /auth` with email, password, and server name
2. **Authentication**: System validates credentials against Active Directory
3. **Authorization**: System checks if user is allowed to access the specified server/service
4. **User Creation/Retrieval**: System retrieves or creates user record in the database
5. **Token Generation**: System generates a JWT token with user ID and hex value
6. **Response**: Returns user information including the JWT token

---

## JWT Token Structure

The JWT token contains the following payload:

```ts
{
  sub: string;  // user ID
  hex: string;  // hexadecimal string associated with the user
}
```

The token expires based on the `JWT_DURATION` configuration setting.

---

## Security Considerations

- Passwords are validated against Active Directory and never stored in plain text in the database
- JWT tokens are signed using the `JWT_SECRET` configuration
- Tokens have an expiration time defined by `JWT_DURATION`
- The `hex` value is used for token validation and is refreshed every 9 hours
- Only authorized users with appropriate roles can access protected endpoints
- API key authentication provides an alternative to JWT for service-to-service communication
