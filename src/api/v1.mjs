// 应用 API v1：插件唯一允许 import 的共享模块（插件不直接 import chord，由这里转发）
import { inviteFacet as chordInviteFacet } from "@earendil-works/chord/app";

export { defineFacet } from "@earendil-works/chord";
export { Http } from "@earendil-works/chord/http";
export { shellRoutes } from "./static.mjs";
export { chatRoutes } from "./chat.mjs";
export { moneyRoutes } from "./money.mjs";
export { papersRoutes } from "./papers.mjs";
export { readerRoutes } from "./reader.mjs";

// chord 自带的成员邀请插件（第 1 批接入：成员账号用邀请链接建，见 plugins/invite）
export const inviteFacet = () => chordInviteFacet();
