import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [
    react({
      jsxRuntime: 'automatic',
    }),
  ],
  base: '/ui/',
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api/, '/api'),
      },
      '/health': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    // Vite 8: Oxc minifier (esbuild minify is deprecated).
    minify: true,
    cssCodeSplit: true,
    target: 'es2020',
    rolldownOptions: {
      // lottie-web uses direct eval; previously silenced via esbuild.logOverride.
      checks: { eval: false },
      output: {
        // Vite 8 / Rolldown: object-form manualChunks removed; use codeSplitting.
        codeSplitting: {
          groups: [
            {
              name: 'vendor',
              test: /[/\\]node_modules[/\\](react|react-dom)([/\\]|$)/,
            },
            {
              name: 'ui',
              test: /[/\\]node_modules[/\\]lucide-react([/\\]|$)/,
            },
            {
              name: 'animations',
              test: /[/\\]node_modules[/\\]lottie-react([/\\]|$)/,
            },
          ],
        },
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]',
      },
    },
    chunkSizeWarningLimit: 700,
  },
  optimizeDeps: {
    include: ['react', 'react-dom', 'lucide-react', 'lottie-react'],
  },
});
