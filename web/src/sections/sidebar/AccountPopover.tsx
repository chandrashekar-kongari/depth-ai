"use client";

import { useState } from "react";
import { LOGOUT_DISABLED } from "@/lib/constants";
import { preload } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  checkUserIsNoAuthUser,
  getUserDisplayName,
  getUserEmail,
  logout,
} from "@/lib/users/svc";
import { useUser } from "@/providers/UserProvider";
import { loginPath } from "@/lib/auth/paths";
import {
  Dropdown,
  OverflowText,
  SidebarTab,
  type DropdownMenuItem,
} from "@opal/components";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  SvgExternalLink,
  SvgHelpCircle,
  SvgLogOut,
  SvgSliders,
  SvgSettings,
  SvgUser,
} from "@opal/icons";
import { toast, useSidebarFolded } from "@opal/layouts";
import { useAppPosition } from "@/lib/position/hooks";
import useScreenSize from "@/hooks/useScreenSize";
import { useSettings } from "@/lib/settings/hooks";
import UserAvatar from "@/refresh-components/avatars/UserAvatar";
import { SidebarLoader } from "@opal/loaders";
import { getFirstPermittedAdminRoute } from "@/lib/permissions/utils";
import { useTranslations } from "next-intl";

/** The account menu’s settings and session actions. */
function useSettingsItems(): DropdownMenuItem[] {
  const t = useTranslations("accountPopover");
  const adminLabel = useTranslations("sidebar")("appSidebar.adminPanel.label");
  const { user, userResolution, hasAdminAccess, adminCapabilities } = useUser();
  const settings = useSettings();
  const enterpriseSettings = settings.enterprise;
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isAnonymousUser =
    user?.is_anonymous_user || checkUserIsNoAuthUser(user?.id ?? "");
  const showLogout = user && !isAnonymousUser && !LOGOUT_DISABLED;
  const showLogin = isAnonymousUser;

  const query = searchParams?.toString();
  const currentUrl = query ? `${pathname}?${query}` : pathname;

  const handleLogin = () => {
    router.push(loginPath({ next: currentUrl }));
  };

  const logoutFailedMessage = t("logoutFailed.message");

  const handleLogout = () => {
    logout()
      .then((response) => {
        if (!response?.ok) {
          alert(logoutFailedMessage);
          return;
        }

        // Held on the login button: with SSO as the only way in, an auto
        // start would sign the user straight back in through the IdP session.
        router.push(loginPath({ next: currentUrl, autoRedirectToSso: false }));
      })

      .catch(() => {
        toast.error(logoutFailedMessage);
      });
  };

  return [
    {
      kind: "custom",
      id: "user-email",
      disabled: true,
      render: ({ props }) => (
        <div {...props} className="p-2">
          <OverflowText as="p" font="secondary-action" color="text-04">
            {userResolution === "unavailable"
              ? t("profileUnavailable.title")
              : getUserEmail(user)}
          </OverflowText>
        </div>
      ),
    },
    {
      kind: "group",
      items: [
        {
          kind: "action",
          id: "user-settings",
          icon: SvgSliders,
          title: t("settings.label"),
          href: "/app/settings",
        },
        ...(hasAdminAccess
          ? [
              {
                kind: "action" as const,
                id: "admin-panel",
                icon: SvgSettings,
                title: adminLabel,
                href: getFirstPermittedAdminRoute(adminCapabilities),
              },
            ]
          : []),
        {
          kind: "action",
          id: "help-faq",
          icon: SvgHelpCircle,
          title: t("helpFaq.label"),
          href: "https://docs.onyx.app",
          target: "_blank",
        },
        ...(enterpriseSettings?.custom_help_link_url
          ? [
              {
                kind: "action" as const,
                id: "custom-help-link",
                icon: SvgExternalLink,
                title:
                  enterpriseSettings.custom_help_link_label ||
                  enterpriseSettings.custom_help_link_url,
                href: enterpriseSettings.custom_help_link_url,
                target: "_blank",
              },
            ]
          : []),
        ...(showLogin
          ? [
              {
                kind: "action" as const,
                id: "log-in",
                icon: SvgUser,
                title: t("logIn.label"),
                onSelect: handleLogin,
              },
            ]
          : []),
        ...(showLogout
          ? [
              {
                kind: "action" as const,
                id: "log-out",
                icon: SvgLogOut,
                danger: true,
                title: t("signOut.label"),
                onSelect: handleLogout,
              },
            ]
          : []),
      ],
    },
  ];
}

export interface SettingsProps {
  onShowBuildIntro?: () => void;
}

export default function AccountPopover(_props: SettingsProps) {
  const t = useTranslations("accountPopover");
  const folded = useSidebarFolded();
  const [menuOpen, setMenuOpen] = useState(false);
  const { user, userResolution } = useUser();
  const appPosition = useAppPosition();
  const { isMobile } = useScreenSize();
  const { vectorDbEnabled } = useSettings();
  const userDisplayName =
    userResolution === "unavailable"
      ? t("accountFallback.label")
      : getUserDisplayName(user);

  const handlePopoverOpen = (state: boolean) => {
    if (state) {
      // Prefetch user settings data when popover opens for instant modal display
      preload("/api/user/pats", errorHandlingFetcher);
      preload("/api/federated/oauth-status", errorHandlingFetcher);
      if (vectorDbEnabled) {
        preload("/api/manage/connector-status", errorHandlingFetcher);
      }
      preload("/api/llm/provider", errorHandlingFetcher);
    }
    setMenuOpen(state);
  };
  const items = useSettingsItems();
  if (userResolution === "loading") {
    return <SidebarLoader width="full" folded={folded} />;
  }

  return (
    <Dropdown
      width={60}
      // On a phone the sidebar is the whole screen: the menu opens above
      // the tab rather than beside it.
      side={isMobile ? "top" : "right"}
      align={isMobile ? "start" : "end"}
      tabKey="walk"
      open={menuOpen}
      onOpenChange={handlePopoverOpen}
    >
      <Dropdown.Trigger asChild>
        <div id="depth-user-dropdown">
          <SidebarTab
            icon={(props) => (
              <div className="w-[16px] flex flex-col justify-center items-center">
                <UserAvatar user={user} {...props} size={props.size} />
              </div>
            )}
            type="button"
            selected={menuOpen || appPosition.isUserSettings()}
          >
            {userDisplayName}
          </SidebarTab>
        </div>
      </Dropdown.Trigger>
      <Dropdown.Data
        label={userDisplayName}
        sizePreset="secondary"
        maxHeight="none"
        items={items}
      />
    </Dropdown>
  );
}
