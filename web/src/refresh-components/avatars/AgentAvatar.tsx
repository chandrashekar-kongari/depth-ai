"use client";

import { MinimalAgent } from "@/lib/agents/types";
import { buildAgentAvatarUrl } from "@/lib/agents/utils";
import { DepthActivityIcon } from "@/refresh-components/avatars/DepthActivityIcon";
import { useSettings } from "@/lib/settings/hooks";
import { DEFAULT_AVATAR_SIZE_PX, DEFAULT_AGENT_ID } from "@/lib/constants";
import CustomAgentAvatar from "@/refresh-components/avatars/CustomAgentAvatar";
import Image from "next/image";
import { useTranslations } from "next-intl";

export interface AgentAvatarProps {
  agent: MinimalAgent;
  size?: number;
  isWorking?: boolean;
}

export default function AgentAvatar({
  agent,
  isWorking = false,
  size = DEFAULT_AVATAR_SIZE_PX,
  ...props
}: AgentAvatarProps) {
  const t = useTranslations("common.agentAvatar");
  const { enterprise: enterpriseSettings } = useSettings();

  if (agent.id === DEFAULT_AGENT_ID) {
    return enterpriseSettings?.use_custom_logo ? (
      <div
        className="aspect-square rounded-full overflow-hidden relative"
        style={{ height: size, width: size }}
      >
        <Image
          alt={t("logo.alt")}
          src="/api/enterprise-settings/logo"
          fill
          className="object-cover object-center"
          sizes={`${size}px`}
        />
      </div>
    ) : (
      <DepthActivityIcon active={isWorking} size={size} />
    );
  }

  return (
    <CustomAgentAvatar
      name={agent.name}
      src={agent.uploaded_image_id ? buildAgentAvatarUrl(agent.id) : undefined}
      iconName={agent.icon_name}
      size={size}
      {...props}
    />
  );
}
