<div align="center">

# Bhavya Patel | Portfolio

A responsive, interactive 3D portfolio built with **React** and an **ASP.NET Core (C#)** backend.

[![Live site](https://img.shields.io/badge/Live%20site-bhavyapatel0201.github.io-3A4FE8?style=for-the-badge&logo=githubpages&logoColor=white)](https://bhavyapatel0201.github.io/)

![React](https://img.shields.io/badge/React-20232A?style=flat-square&logo=react&logoColor=61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)
![Three.js](https://img.shields.io/badge/Three.js-000000?style=flat-square&logo=threedotjs&logoColor=white)
![.NET](https://img.shields.io/badge/.NET%208-512BD4?style=flat-square&logo=dotnet&logoColor=white)
![C#](https://img.shields.io/badge/C%23-239120?style=flat-square&logo=csharp&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-07405E?style=flat-square&logo=sqlite&logoColor=white)

</div>

---

## Overview

This is my personal portfolio. The React frontend shows my projects, skills and contact form, and the ASP.NET Core Web API serves the project and skill data and handles contact messages. If the API is unreachable, the frontend falls back to local data, so the site still works when hosted statically.

## Features

- **3D hero scene** built with Three.js: a glowing core, orbit rings, floating shards that react to the cursor, and a particle field that responds to scrolling
- **Responsive layout** tested from 375px phones to 1440px desktops, with a mobile menu and fluid typography
- **Dark and light themes** that follow the system setting and remember the visitor's choice
- **Interactive projects**: tag filters, 3D tilt cards and a details modal
- **Contact form** with validation, rate limiting and email delivery through the API
- **Accessible by design**: semantic HTML, keyboard focus states, WCAG AA contrast and reduced-motion support
- **REST API** with Swagger documentation, validation, global error handling and unit tests

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, TypeScript, React Router, Tailwind CSS, Framer Motion |
| 3D | Three.js with `@react-three/fiber` and `@react-three/drei` |
| Backend | ASP.NET Core Web API on .NET 8, C# |
| Data | Entity Framework Core with SQLite |
| Validation and tests | FluentValidation, xUnit |
| Hosting | GitHub Pages (frontend), Azure App Service or Render (API) |

## Project structure

```
portfolio/
├── client/                 # React app (Vite + TypeScript)
│   ├── src/
│   │   ├── components/     # UI sections and the 3D scene
│   │   ├── data/           # Fallback content used if the API is down
│   │   ├── lib/            # Typed API client
│   │   └── styles/         # Design tokens and global styles
│   └── .env.example
├── server/                 # ASP.NET Core Web API
│   ├── Controllers/        # HTTP endpoints
│   ├── Services/           # Business logic (contact, email)
│   ├── Data/               # DbContext, migrations, seed data
│   ├── Models/             # Entities and DTOs
│   └── appsettings.json
├── server.Tests/           # xUnit tests
└── README.md
```

## Getting started

### Prerequisites

- [.NET 8 SDK](https://dotnet.microsoft.com/download) (`dotnet --version`)
- [Node.js LTS](https://nodejs.org/) (`node --version`)
- Git

### 1. Clone the repository

```bash
git clone https://github.com/bhavyapatel0201/portfolio.git
cd portfolio
```

### 2. Run the API

```bash
cd server
dotnet restore
dotnet ef database update      # creates and seeds the SQLite database
dotnet run
```

The console prints the local URL. Swagger is available at `/swagger`.

To enable contact-form emails, store your SMTP settings in user secrets. Never commit them.

```bash
dotnet user-secrets set "Smtp:Host" "smtp.example.com"
dotnet user-secrets set "Smtp:Port" "587"
dotnet user-secrets set "Smtp:Username" "your-username"
dotnet user-secrets set "Smtp:Password" "your-password"
dotnet user-secrets set "Contact:Recipient" "you@example.com"
```

### 3. Run the frontend

In a second terminal:

```bash
cd client
npm install
cp .env.example .env           # then set VITE_API_URL to the URL the API printed
npm run dev
```

Open the address that Vite prints, usually `http://localhost:5173`.

## Configuration

| Variable | Where | Purpose |
|---|---|---|
| `VITE_API_URL` | `client/.env` | Base URL of the API |
| `Cors:AllowedOrigin` | `server/appsettings.json` | Frontend origin allowed to call the API |
| `Smtp:*`, `Contact:Recipient` | user secrets or environment variables | Email delivery for the contact form |

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/projects` | List projects, with an optional `?tag=` filter |
| GET | `/api/projects/{id}` | Get one project |
| GET | `/api/skills` | List skills by category |
| POST | `/api/contact` | Submit a contact message (validated and rate limited) |
| GET | `/api/health` | Health check |

## Testing

```bash
dotnet test server.Tests
```

## Deployment

- **Frontend:** a GitHub Actions workflow builds `client/` and publishes it to GitHub Pages. In the repository settings, set Pages to deploy from GitHub Actions.
- **API:** publish `server/` to Azure App Service or Render, set the environment variables above, then point `VITE_API_URL` at the deployed API and allow the Pages origin in `Cors:AllowedOrigin`.

## Roadmap

- [ ] Add detailed case studies for each project
- [ ] Add a blog section
- [ ] Add analytics that respect visitor privacy

## Contact

- Portfolio: [bhavyapatel0201.github.io](https://bhavyapatel0201.github.io/)
- LinkedIn: [bhavya-patel-data](https://www.linkedin.com/in/bhavya-patel-data/)
- GitHub: [@bhavyapatel0201](https://github.com/bhavyapatel0201)

## License

Released under the MIT License. See `LICENSE` for details.
