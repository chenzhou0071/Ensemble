// vitest 专用入口：从 vitest 导入 expect 扩展 matcher（globals: false 下主入口会报 expect is not defined）。
import "@testing-library/jest-dom/vitest";
