import { configDefaults, defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // Agent worktree nusxalari (.claude/worktrees) testlari ikki marta yurmasin.
    exclude: [...configDefaults.exclude, '.claude/**'],
  },
})
