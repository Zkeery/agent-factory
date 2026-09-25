import { test, expect } from "@playwright/test";

test("完整闭环：登录 → 提交想法 → 决策卡快捷按钮 → PRD → 确认 → 验收 → 完成", async ({ page }) => {
  await page.goto("/");

  // 手机号验证码登录（mock 短信：验证码自动填入）
  await page.fill('input[placeholder="手机号"]', "13800138000");
  await page.getByRole("button", { name: "获取验证码", exact: true }).click();
  const codeInput = page.locator('input[placeholder="验证码"]');
  await codeInput.waitFor({ timeout: 10_000 });
  await expect(codeInput).not.toHaveValue("");
  await page.getByRole("button", { name: "登录", exact: true }).click();

  // 固定用本地 Mock（全局默认是 deepseek，会走真实模型：慢、花钱、结果不确定）
  await page.getByLabel("选择本轮模型").selectOption("mock");

  // 输入想法并发送（对话式工作台底部输入框）
  await page.fill('input[placeholder*="给造物坊 AI 发消息"]', "做一个给宠物起名字的小工具");
  await page.keyboard.press("Enter");

  // 等决策卡快捷按钮出现
  await expect(page.getByRole("button", { name: "按推荐", exact: true }).first()).toBeVisible({ timeout: 20_000 });

  // 非关键决策已由 AI 自动按推荐处理（决策卡 A+B 的 B 部分），并提供「改」按钮
  await expect(page.getByText("已按推荐自动").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "改", exact: true }).first()).toBeVisible();

  // 逐张点「按推荐」（mock 固定 3 张决策卡，多留 2 次余量）
  for (let i = 0; i < 5; i++) {
    const btn = page.getByRole("button", { name: "按推荐", exact: true });
    if ((await btn.count()) === 0) break;
    await btn.first().click();
    await page.waitForTimeout(800);
  }

  // 等 PRD 卡片与确认按钮出现
  await expect(page.getByRole("button", { name: "确认 PRD", exact: true })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "确认 PRD", exact: true }).click();

  // 确认后流水线跑到待验收，勾选三项清单后交付
  await expect(page.getByRole("button", { name: "验收通过，交付", exact: true })).toBeVisible({ timeout: 30_000 });
  for (const cb of await page.getByRole("checkbox").all()) {
    await cb.check();
  }
  const acceptBtn = page.getByRole("button", { name: "验收通过，交付", exact: true });
  await expect(acceptBtn).toBeEnabled();
  await acceptBtn.click();

  // 交付完成消息
  await expect(page.getByText("已验收交付。可预览运行成品。")).toBeVisible({ timeout: 30_000 });
});
