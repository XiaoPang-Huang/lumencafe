import { defineFacet, Http, modelRoutes } from "@lumencafe/app/v1";

// 模型 & API 管理插件（需求-模型API管理-v1.md）：供应商/套餐/模型/授权/日志 + 个人模型
export default defineFacet((host, self) => {
  self.contribute(Http, { routes: modelRoutes() });
});
