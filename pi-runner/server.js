/**
 * pi-runner：Pi SDK 进程内嵌入 + Fastify HTTP 薄层（开发计划-pi-runner-v1 步 2）。
 *
 * 三端点（主体只面对这三个）：
 *   POST /api/runs            { run_id, task } → 202（run_id 幂等，重复提交返回已有 run）
 *   GET  /api/runs/:id/events → SSE 转发 session.subscribe() 事件流
 *   POST /api/runs/:id/abort  → session.abort()
 * 结果落盘 /output/<run_id>/：result.md（最终正文）+ events.jsonl（全量事件）。
 *
 * 装配注意（落地方案 §2 必做项）：SDK session 默认不加载内建 MCP / codemode /
 * tool-search——必须显式加入 DefaultResourceLoader.extensionFactories 并
 * session.bindExtensions()，否则 MCP 工具对模型不可见且不报错。
 */
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import Fastify from "fastify";
import {
	createAgentSession,
	createCodemodeExtension,
	createMcpExtension,
	createToolSearchExtension,
	DefaultResourceLoader,
	getAgentDir,
	SessionManager,
	SettingsManager,
} from "@earendil-works/pi-coding-agent";

const PORT = Number(process.env.PORT || 8787);
const OUTPUT_DIR = process.env.OUTPUT_DIR || "/output";
const WORKSPACE_DIR = process.env.WORKSPACE_DIR || "/workspace";

/** @type {Map<string, {status: string, session: any, events: Array, reply: import("fastify").FastifyReply | null, task: string, error: string | null, startedAt: string, finishedAt: string | null}>} */
const runs = new Map();

const app = Fastify({ logger: true });

app.get("/healthz", async () => ({ ok: true }));

/**
 * 创建并跑一个 run：每个 run 独立 session（in-memory、cwd=/workspace），
 * 事件先进内存缓冲区（供断线重连回放），同时广播给挂起的 SSE 连接。
 */
async function createRun(runId, task) {
	const resourceLoader = new DefaultResourceLoader({
		cwd: WORKSPACE_DIR,
		agentDir: getAgentDir(),
		extensionFactories: [
			createCodemodeExtension({ mode: "on" }),
			createToolSearchExtension(),
			// 读 agentDir 的 mcp.json（步 4 起接 paper-search-mcp / Playwright）
			createMcpExtension(),
		],
	});
	await resourceLoader.reload();

	const settingsManager = SettingsManager.create(WORKSPACE_DIR);
	// +name = 在默认工具集上追加（tools 会替换成白名单，隐藏 MCP 工具）
	settingsManager.applyOverrides({ defaultTools: ["+codemode", "+tool_search"] });

	const { session } = await createAgentSession({
		resourceLoader,
		settingsManager,
		sessionManager: SessionManager.inMemory(),
		cwd: WORKSPACE_DIR,
	});

	const run = {
		status: "starting",
		session,
		events: [],
		listeners: new Set(),
		task,
		error: null,
		startedAt: new Date().toISOString(),
		finishedAt: null,
	};
	runs.set(runId, run);

	// MCP 扩展在 session_start 事件里连接 server，必须先 bind
	await session.bindExtensions({});

	let textBuf = "";
	let resultWritten = false;
	const persistResult = async () => {
		if (resultWritten) return;
		resultWritten = true;
		const dir = path.join(OUTPUT_DIR, runId);
		await mkdir(dir, { recursive: true });
		await writeFile(path.join(dir, "result.md"), textBuf, "utf8");
		await writeFile(
			path.join(dir, "events.jsonl"),
			run.events.map((e) => JSON.stringify(e)).join("\n") + "\n",
			"utf8",
		);
	};

	const pushEvent = (event) => {
		let serializable = event;
		try {
			JSON.stringify(event);
		} catch {
			serializable = { type: "unserializable", detail: String(event) };
		}
		run.events.push(serializable);
		for (const listener of run.listeners) listener(serializable);
		// 流式正文增量 → result.md 原料
		if (
			event?.type === "message_update" &&
			event.assistantMessageEvent?.type === "text_delta"
		) {
			textBuf += event.assistantMessageEvent.delta;
		}
	};

	session.subscribe(pushEvent);
	run.status = "running";

	session
		.prompt(task)
		.then(async () => {
			run.status = run.aborted ? "aborted" : "completed";
			run.finishedAt = new Date().toISOString();
			pushEvent({ type: "run_end", status: "completed", runId });
			await persistResult();
		})
		.catch(async (err) => {
			run.status = "failed";
			run.error = String(err?.message || err);
			run.finishedAt = new Date().toISOString();
			pushEvent({ type: "run_end", status: "failed", runId, error: run.error });
			await persistResult();
		})
		.finally(() => {
			// 事件全部推完后断开 SSE，session 随之释放
			setTimeout(() => {
				for (const listener of run.listeners) listener({ type: "sse_close" });
				run.listeners.clear();
				// dispose() 同步返回 void（非 Promise），不得挂 .catch
				try {
					session.dispose();
				} catch {
					/* 会话已释放 */
				}
			}, 500);
		});

	return run;
}

app.post("/api/runs", async (req, reply) => {
	const { run_id: runId, task } = req.body || {};
	if (!runId || typeof runId !== "string" || !task || typeof task !== "string") {
		return reply.code(400).send({ error: "body 需含 run_id 与 task（字符串）" });
	}
	if (runs.has(runId)) {
		const existing = runs.get(runId);
		return reply.code(200).send({
			run_id: runId,
			status: existing.status,
			idempotent: true,
		});
	}
	try {
		const run = await createRun(runId, task);
		return reply.code(202).send({ run_id: runId, status: run.status });
	} catch (err) {
		req.log.error(err);
		return reply.code(500).send({ error: String(err?.message || err) });
	}
});

app.get("/api/runs/:id/events", async (req, reply) => {
	const run = runs.get(req.params.id);
	if (!run) return reply.code(404).send({ error: "run 不存在" });

	reply.raw.writeHead(200, {
		"Content-Type": "text/event-stream",
		"Cache-Control": "no-cache",
		Connection: "keep-alive",
		"X-Accel-Buffering": "no",
	});
	reply.hijack();

	const send = (event) => {
		reply.raw.write(`data: ${JSON.stringify(event)}\n\n`);
		if (event?.type === "sse_close") reply.raw.end();
	};
	// 回放缓冲区历史事件，再挂实时监听
	for (const event of run.events) send(event);
	run.listeners.add(send);
});

app.post("/api/runs/:id/abort", async (req, reply) => {
	const run = runs.get(req.params.id);
	if (!run) return reply.code(404).send({ error: "run 不存在" });
	run.aborted = true;
	try {
		await run.session.abort();
		return reply.send({ run_id: req.params.id, status: "aborted" });
	} catch (err) {
		return reply.code(500).send({ error: String(err?.message || err) });
	}
});

app.get("/api/runs/:id", async (req, reply) => {
	const run = runs.get(req.params.id);
	if (!run) return reply.code(404).send({ error: "run 不存在" });
	return reply.send({
		run_id: req.params.id,
		status: run.status,
		error: run.error,
		events: run.events.length,
		startedAt: run.startedAt,
		finishedAt: run.finishedAt,
	});
});

app.listen({ port: PORT, host: "0.0.0.0" }).catch((err) => {
	console.error(err);
	process.exit(1);
});
