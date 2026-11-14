import { defineFacet, Http, chatRoutes, agentRoutes } from "@lumencafe/app/v1";

// 对话应用插件（第 1 批单次调用 + 第 5 批 agent 模式）：逻辑在 src/api/chat.mjs / agent.mjs
export default defineFacet((host, self) => {
  self.contribute(Http, { routes: { ...chatRoutes(), ...agentRoutes() } });
});
