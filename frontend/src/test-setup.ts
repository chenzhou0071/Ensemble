// vitest 专用入口：从 vitest 导入 expect 扩展 matcher（globals: false 下主入口会报 expect is not defined）。
import "@testing-library/jest-dom/vitest";

// globals: false 下 RTL 不会自动 cleanup（它依赖全局 afterEach），需显式注册，
// 否则多用例间 DOM 残留，查询会命中重复元素。
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());
