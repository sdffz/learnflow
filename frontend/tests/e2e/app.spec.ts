import { expect, test } from "@playwright/test";

let userSequence = 0;

async function registerAccount(page: import("@playwright/test").Page) {
  userSequence += 1;
  const email = `e2e-${Date.now()}-${Math.random()
    .toString(36)
    .slice(2)}-${userSequence}@example.com`;
  await page.goto("/");
  await page.getByText("登录你的知识空间").waitFor();
  await page.getByRole("button", { name: "创建账号" }).click();
  await page.getByLabel("姓名").fill("测试同学");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码", { exact: true }).fill("EnterprisePass123!");
  await page
    .getByLabel("确认密码", { exact: true })
    .fill("EnterprisePass123!");
  await page.getByRole("button", { name: "注册并进入" }).click();
  await page.getByText("个人知识工作台").waitFor();
  return { email, password: "EnterprisePass123!" };
}

test("home page loads without missing static resources", async ({ page }) => {
  const failures: string[] = [];
  page.on("response", (response) => {
    if (
      !response.url().includes("/api/") &&
      response.status() >= 400
    ) {
      failures.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto("/");
  await page.waitForLoadState("networkidle");

  expect(failures).toEqual([]);
});

test("personal knowledge main flow", async ({ page }) => {
  await registerAccount(page);

  await page.getByRole("button", { name: "打开添加知识" }).click();
  const dialog = page.getByRole("dialog", { name: "添加知识" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("tab", { name: "快速笔记" }).click();
  const folderSelect = dialog.getByRole("combobox");
  const folderName = await folderSelect.locator("option").first().innerText();
  await folderSelect.selectOption({ index: 0 });
  await page.getByLabel("资料标题", { exact: true }).fill("监督学习课堂笔记");
  await page.getByLabel("资料内容", { exact: true }).fill(
    "监督学习使用带标签数据训练模型，目标是学习输入到标签的映射。",
  );
  await page.getByLabel("标签", { exact: true }).fill("机器学习,监督学习");
  await page.getByRole("button", { name: "保存笔记" }).click();
  await expect(page.getByRole("status")).toContainText("已入库");
  await page.getByRole("button", { name: "关闭添加知识" }).click();

  await page
    .getByRole("button", { name: "知识文件夹", exact: true })
    .click();
  await page.getByRole("button", { name: "打开文件夹" }).first().click();
  await expect(page.getByText("文件夹知识点")).toBeVisible();
  await expect(page.getByText("监督学习课堂笔记").first()).toBeVisible();
  await page.getByRole("button", { name: "返回知识文件夹" }).click();

  await page.getByRole("button", { name: "知识库", exact: true }).click();
  await page
    .getByPlaceholder("搜索文件夹、资料、标签或正文")
    .fill("带标签数据");
  await page.getByRole("button", { name: "搜索" }).click();
  await expect(
    page.getByText(`${folderName} · 监督学习课堂笔记`).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "打开来源" }).first().click();
  await expect(
    page.getByRole("heading", { name: "监督学习课堂笔记" }),
  ).toBeVisible();
  await expect(
    page.getByText(/监督学习使用带标签数据训练模型/).first(),
  ).toBeVisible();
});

test("personal learner can complete the learning agent loop", async ({
  page,
}) => {
  await registerAccount(page);

  await page.getByRole("button", { name: "打开添加知识" }).click();
  const capture = page.getByRole("dialog", { name: "添加知识" });
  await capture.getByRole("tab", { name: "快速笔记" }).click();
  await capture.getByRole("combobox").selectOption({ index: 0 });
  await capture.getByLabel("资料标题", { exact: true }).fill("神经网络个人笔记");
  await capture
    .getByLabel("资料内容", { exact: true })
    .fill("神经网络通过多层单元学习特征，并用反向传播调整参数。");
  await capture.getByLabel("标签", { exact: true }).fill("神经网络");
  await page.getByRole("button", { name: "保存笔记" }).click();
  await expect(capture.getByRole("status")).toContainText("已入库");
  await page.getByRole("button", { name: "关闭添加知识" }).click();

  await page.getByRole("button", { name: "学习画像", exact: true }).click();
  await page.getByRole("button", { name: "建立我的学习画像" }).click();
  await expect(page.getByText("让系统先认识你")).toBeVisible();

  await page
    .getByPlaceholder("描述你的学习情况")
    .fill(
      "我零基础刚接触，大一，想完成项目，喜欢视频动画和图解，神经网络比较弱，每周学习6小时，希望做机器人项目。",
    );
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("8 / 8 维画像")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "用画像生成资源" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "用画像生成资源" }).click();
  await page.getByRole("button", { name: "生成六类资源" }).click();
  await expect(page.getByRole("tab", { name: "动画微课" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("学习资源 6/6")).toBeVisible();
  await expect(
    page.getByText("知识来源", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/神经网络个人笔记/).first(),
  ).toBeVisible();

  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "智能生成", exact: true }).click();
  await expect(page.getByRole("tab", { name: "动画微课" })).toBeVisible();

  await page.getByRole("button", { name: "智能辅导", exact: true }).click();
  await page.getByPlaceholder("向课程知识库提问").fill("什么是监督学习？");
  await page.getByRole("button", { name: "提问" }).click();
  await expect(page.getByText(/^根据课程资料：监督学习/)).toBeVisible();

  await page.getByRole("button", { name: "学习计划", exact: true }).click();
  await expect(page.getByText("建立人工智能的基本坐标系")).toBeVisible();
  await expect(page.getByText("当前节点")).toBeVisible();

  await page.getByRole("button", { name: "进入学习评估" }).click();
  await expect(
    page.getByText("监督学习与无监督学习最关键的差别是什么？"),
  ).toBeVisible();
  await page.getByRole("button", { name: /是否使用带标签数据/ }).click();
  await page.getByRole("button", { name: /估计剩余代价以引导搜索/ }).click();
  await page.getByRole("button", { name: /^A 0$/ }).click();
  await page.getByRole("button", { name: /训练集很好但验证集明显较差/ }).click();
  await page
    .getByRole("button", { name: /配合权限控制、日志脱敏和最小数据原则/ })
    .click();
  await page.getByRole("button", { name: "提交并更新画像" }).click();
  await expect(page.getByText("掌握正在成形")).toBeVisible();
  await page.getByRole("button", { name: "返回学习工作台" }).click();

  await page.getByRole("button", { name: "知识首页", exact: true }).click();
  await expect(page.getByText("个人知识工作台")).toBeVisible();
});

for (const viewport of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
]) {
  test(`learning connector wizard works on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await registerAccount(page);
    let loginPolls = 0;
    await page.route("**/api/learning/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const fulfill = (body: unknown, status = 200) =>
        route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(body),
        });

      if (path.endsWith("/learning/chaoxing/status")) {
        return fulfill({ enabled: true, connection: null });
      }
      if (path.endsWith("/learning/chaoxing/login") && request.method() === "POST") {
        return fulfill(
          {
            id: "login-e2e",
            status: "pending",
            expiresAt: new Date(Date.now() + 300_000).toISOString(),
            revision: 0,
          },
          201,
        );
      }
      if (path.endsWith("/learning/chaoxing/login/login-e2e/qr")) {
        return route.fulfill({
          status: 200,
          contentType: "image/svg+xml",
          body: '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240"><rect width="240" height="240" fill="#fff"/></svg>',
        });
      }
      if (path.endsWith("/learning/chaoxing/login/login-e2e")) {
        loginPolls += 1;
        if (loginPolls === 1) {
          return fulfill({
            status: "pending",
            remoteNickname: null,
            message: null,
          });
        }
        return fulfill({
          status: "connected",
          remoteNickname: "林同学",
          message: null,
        });
      }
      if (path.endsWith("/learning/chaoxing/previews") && request.method() === "POST") {
        return fulfill(
          {
            id: "preview-e2e",
            courses: [
              {
                id: "course-e2e",
                title: "高等数学",
                teacher: "张老师",
                documents: [
                  {
                    id: "file-e2e",
                    name: "第一章.pdf",
                    extension: ".pdf",
                    sizeBytes: 2048,
                    supported: true,
                    excludedReason: null,
                  },
                ],
                videoLinks: ["https://mooc1.chaoxing.com/video/1.mp4"],
              },
            ],
            totalDocuments: 1,
            totalVideoLinks: 1,
            totalBytes: 2048,
            generatedAt: new Date().toISOString(),
            expiresAt: new Date(Date.now() + 1_800_000).toISOString(),
          },
          201,
        );
      }
      if (path.endsWith("/learning/imports") && request.method() === "POST") {
        return fulfill(
          {
            id: "job-e2e",
            previewId: "preview-e2e",
            status: "queued",
            progress: 0,
            totalItems: 2,
            completedItems: 0,
            failedItems: 0,
            skippedItems: 0,
            cancelRequested: false,
            createdAt: new Date().toISOString(),
            startedAt: null,
            finishedAt: null,
            errorCode: null,
            errorMessage: null,
          },
          201,
        );
      }
      if (path.endsWith("/learning/imports/job-e2e")) {
        return fulfill({
          job: {
            id: "job-e2e",
            previewId: "preview-e2e",
            status: "completed",
            progress: 100,
            totalItems: 2,
            completedItems: 2,
            failedItems: 0,
            skippedItems: 0,
            cancelRequested: false,
            createdAt: new Date().toISOString(),
            startedAt: new Date().toISOString(),
            finishedAt: new Date().toISOString(),
            errorCode: null,
            errorMessage: null,
          },
          items: [
            {
              id: "job-item-e2e",
              jobId: "job-e2e",
              kind: "file",
              title: "第一章.pdf",
              externalCourseId: "course-e2e",
              externalFileId: "file-e2e",
              targetCourseId: "target-e2e",
              status: "completed",
              attempts: 1,
              checksum: "abc",
              assetId: "asset-e2e",
              errorCode: null,
              errorMessage: null,
              sizeBytes: 2048,
              createdAt: new Date().toISOString(),
              updatedAt: new Date().toISOString(),
            },
          ],
        });
      }
      return fulfill({ detail: "not_found" }, 404);
    });

    await page
      .getByRole("button", { name: "知识文件夹", exact: true })
      .click();
    await page.getByRole("button", { name: "连接学习通" }).click();
    const dialog = page.getByRole("dialog", { name: "从学习通导入课程资料" });
    await dialog.getByRole("button", { name: "生成学习通二维码" }).click();
    await expect(dialog.getByAltText("学习通扫码登录二维码")).toBeVisible();
    await expect(dialog.getByText("选择要导入的课程")).toBeVisible({
      timeout: 10_000,
    });
    await dialog.getByRole("checkbox", { name: /高等数学/ }).check();
    await dialog.getByRole("button", { name: "下一步：设置文件夹" }).click();
    await dialog.getByRole("button", { name: "确认导入" }).click();
    await expect(
      dialog.getByRole("heading", { name: "导入完成" }),
    ).toBeVisible({ timeout: 10_000 });
    await dialog.getByRole("button", { name: "查看导入资料" }).click();
    await expect(dialog).not.toBeVisible();

    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    expect(hasHorizontalOverflow).toBe(false);
  });
}
