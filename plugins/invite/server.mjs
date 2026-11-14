import { inviteFacet } from "@lumencafe/app/v1";

// chord 自带的成员邀请插件（第 1 批接入）：
// 主人 POST /_chord/invites {principal:{kind:"member",name:"..."}, label:"..."} 建邀请，
// 成员打开邀请链接即获得会话（principal 由主人指定，名字带在身上）。
export default inviteFacet();
