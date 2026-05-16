# Text2SQL Frontend

Modern React + TypeScript frontend for the Text2SQL Natural Language to SQL system.

## Features

- 🎨 **Beautiful UI** - Gradient-based design with smooth animations
- 💬 **Chat Interface** - ChatGPT-like conversational UI
- 📝 **Markdown Support** - Rich text and code block rendering
- 🎯 **SQL Highlighting** - Syntax highlighting for SQL queries
- 📊 **CSV Export** - Download query results as CSV files
- 🌙 **Dark Mode** - Full dark mode support
- ⚡ **Fast** - Built with Vite for instant HMR
- 📱 **Responsive** - Works on all device sizes

## Tech Stack

- **React 18** - UI library
- **TypeScript** - Type safety
- **Vite** - Build tool and dev server
- **TailwindCSS** - Utility-first CSS
- **Framer Motion** - Animations
- **React Query** - Data fetching and caching
- **Zustand** - State management
- **React Markdown** - Markdown rendering
- **Prism** - Code syntax highlighting
- **Lucide Icons** - Beautiful icons

## Getting Started

### Prerequisites

- Node.js 18+ or Bun
- npm, yarn, pnpm, or bun

### Installation

```bash
# Install dependencies
npm install
# or
yarn install
# or
pnpm install
# or
bun install
```

### Development

```bash
# Start dev server (http://localhost:3000)
npm run dev
```

The frontend will proxy API requests to `http://localhost:18001` (backend).

### Build

```bash
# Type check
npm run type-check

# Build for production
npm run build

# Preview production build
npm run preview
```

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── ui/           # Reusable UI components
│   │   │   ├── Button.tsx
│   │   │   ├── Textarea.tsx
│   │   │   └── Card.tsx
│   │   └── chat/         # Chat-specific components
│   │       ├── ChatContainer.tsx
│   │       ├── ChatInput.tsx
│   │       ├── ChatMessage.tsx
│   │       ├── CodeBlock.tsx
│   │       └── MessageContent.tsx
│   ├── hooks/            # Custom React hooks
│   │   └── useChat.ts
│   ├── services/         # API client
│   │   └── api.ts
│   ├── store/            # Zustand stores
│   │   └── chatStore.ts
│   ├── types/            # TypeScript types
│   │   └── message.ts
│   ├── utils/            # Utility functions
│   │   ├── cn.ts
│   │   └── download.ts
│   ├── App.tsx           # Main app component
│   ├── main.tsx          # Entry point
│   └── index.css         # Global styles
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
└── tailwind.config.js
```

## API Integration

The frontend communicates with the backend via REST API:

- **POST /api/messages** - Send chat messages
- **GET /api/health** - Health check

Response format:
```typescript
interface Message {
  role: 'user' | 'assistant';
  content: string;
  type: 'sql' | 'plain';
  download_link?: string | null;
}
```

## Customization

### Colors

Edit `tailwind.config.js` to customize the color scheme:

```js
theme: {
  extend: {
    colors: {
      primary: { /* ... */ },
      secondary: { /* ... */ },
    }
  }
}
```

### Animations

Framer Motion animations can be customized in component files. Check `ChatMessage.tsx` and `ChatContainer.tsx` for examples.

## Best Practices

- **TypeScript** - Full type safety throughout
- **Component Composition** - Small, reusable components
- **Custom Hooks** - Business logic separated from UI
- **Error Handling** - Comprehensive error states
- **Loading States** - Proper loading indicators
- **Accessibility** - Semantic HTML and ARIA labels

## Contributing

1. Follow the existing code style
2. Use TypeScript for type safety
3. Add proper error handling
4. Test responsiveness on different screen sizes
5. Ensure dark mode compatibility

## License

Same as the main Text2SQL project.
