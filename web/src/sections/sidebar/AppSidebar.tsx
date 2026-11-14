"use client";

import {
  useCallback,
  useState,
  useEffect,
  useLayoutEffect,
  useRef,
} from "react";
import { useReviewAvailability } from "@/lib/engineering/hooks";
import useNotifications from "@/hooks/useNotifications";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import ChatButton from "@/sections/sidebar/ChatButton";
import useChatSessions from "@/hooks/useChatSessions";
import { SidebarLoader } from "@opal/loaders";
import { SidebarLayouts } from "@opal/layouts";
import BrandedSidebarHeader from "@/sections/sidebar/BrandedSidebarHeader";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";
import { Disabled } from "@opal/core";
import { usePlans, useTierAtLeast } from "@/lib/tiers/hooks";
import { BetaTag, PlanTag } from "@/lib/tiers/components";
import { Tier } from "@/lib/tiers/types";
import { PHFeatureFlag, usePHFeatureFlag } from "@/lib/analytics/hooks";
import { SidebarTab } from "@opal/components";
import { ChatSession } from "@/app/app/types";
import { useUser } from "@/providers/UserProvider";
import { useAppPosition } from "@/lib/position/hooks";
import { useModalContext } from "@/components/context/ModalContext";
import { SvgDevKit, SvgPlus, SvgSearchMenu } from "@opal/icons";
import BuildModeIntroBackground from "@/app/craft/components/IntroBackground";
import BuildModeIntroContent from "@/app/craft/components/IntroContent";
import { CRAFT_PATH } from "@/app/craft/v1/constants";
import UnseenMarker from "@/app/craft/components/UnseenMarker";
import { Section } from "@/layouts/general-layouts";
import { useUnviewedScheduledTaskCount } from "@/lib/scheduledTasks/hooks";
import { track, AnalyticsEvent } from "@/lib/analytics/utils";
import { motion, AnimatePresence } from "motion/react";
import { NotificationType } from "@/lib/notifications/interfaces";
import { dismissNotification } from "@/lib/notifications/api";
import AccountPopover from "@/sections/sidebar/AccountPopover";
import ChatSearchCommandMenu from "@/sections/sidebar/ChatSearchCommandMenu";
import { useQueryController } from "@/providers/QueryControllerProvider";

interface RecentsSectionProps {
  chatSessions: ChatSession[];
  isLoading: boolean;
  hasMore: boolean;
  isLoadingMore: boolean;
  onLoadMore: () => void;
}

function RecentsSection({
  chatSessions,
  isLoading,
  hasMore,
  isLoadingMore,
  onLoadMore,
}: RecentsSectionProps) {
  const t = useTranslations("sidebar");
  // Sentinel ref for IntersectionObserver-based infinite scroll
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const onLoadMoreRef = useRef(onLoadMore);

  // Layout effect: an already-scheduled observer callback must not see the
  // previous page's loadMore after commit.
  useLayoutEffect(() => {
    onLoadMoreRef.current = onLoadMore;
  }, [onLoadMore]);

  useEffect(() => {
    if (!hasMore || isLoadingMore) return;

    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          onLoadMoreRef.current();
        }
      },
      { threshold: 0 }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, isLoadingMore]);

  return (
    <SidebarLayouts.Section title={t("appSidebar.recents.title")}>
      {isLoading ? (
        <SidebarLoader count={5} />
      ) : chatSessions.length === 0 ? (
        <div className="px-3">
          <Text as="p" color="text-01">
            {t("appSidebar.recents.empty.text")}
          </Text>
        </div>
      ) : (
        <>
          {chatSessions.map((chatSession) => (
            <ChatButton key={chatSession.id} chatSession={chatSession} />
          ))}
          {hasMore && (
            <div
              ref={sentinelRef}
              // Waiting to scroll into view, nothing is loading yet.
              aria-hidden={!isLoadingMore}
              className={cn(
                "transition-opacity duration-300",
                isLoadingMore ? "opacity-100" : "opacity-40"
              )}
            >
              <SidebarLoader count={3} />
            </div>
          )}
        </>
      )}
    </SidebarLayouts.Section>
  );
}

export default function AppSidebar() {
  const reviewLabels = useTranslations("engineeringReviews");
  const reviewAvailability = useReviewAvailability();
  const t = useTranslations("sidebar");
  const tCraftUpgrade = useTranslations("craft.upgrade");
  const router = useRouter();
  const combinedSettingsData = useSettings();
  const { newTenantInfo, invitationInfo } = useModalContext();
  const { setAppMode, reset } = useQueryController();

  // Use SWR hooks for data fetching
  const {
    chatSessions,
    isLoading: isLoadingChatSessions,
    hasMore,
    isLoadingMore,
    loadMore,
  } = useChatSessions();
  // Check if Depth Craft is enabled via settings (backed by PostHog feature flag)
  // Only explicit true enables the feature; false or undefined = disabled
  const isDepthCraftEnabled = combinedSettingsData?.onyx_craft_enabled === true;
  const isDepthCraftUpsell =
    !isDepthCraftEnabled &&
    combinedSettingsData?.onyx_craft_requires_upgrade === true;
  // Gated like a Business admin page: below that tier the tab is disabled.
  const hasCraftTier = useTierAtLeast(Tier.BUSINESS);
  const tTasks = useTranslations("craft.tasks");
  const unviewedTaskCount = useUnviewedScheduledTaskCount(
    isDepthCraftEnabled && hasCraftTier
  );
  const plans = usePlans();

  // Fetch notifications for build mode intro
  const { notifications, refresh: mutateNotifications } = useNotifications({
    enabled: isDepthCraftEnabled,
  });

  // Find build_mode feature announcement notification (only if Depth Craft is enabled)
  const buildModeNotification = isDepthCraftEnabled
    ? notifications?.find(
        (n) =>
          n.notif_type === NotificationType.FEATURE_ANNOUNCEMENT &&
          n.additional_data?.feature === "build_mode" &&
          !n.dismissed
      )
    : undefined;

  // State for intro animation overlay
  const [showIntroAnimation, setShowIntroAnimation] = useState(false);
  // Track if auto-trigger has fired (prevents race condition during dismiss)
  const hasAutoTriggeredRef = useRef(false);

  // Auto-show intro once when there's an undismissed notification
  // Don't show if tenant/invitation modal is open (e.g., "join existing team" modal)
  // Gated by PostHog feature flag: if `craft-animation-disabled` is true (or
  // PostHog is unavailable), skip the auto-show entirely.
  const isCraftAnimationDisabled = usePHFeatureFlag(
    PHFeatureFlag.CRAFT_ANIMATION_DISABLED
  );
  const hasTenantModal = !!(newTenantInfo || invitationInfo);
  useEffect(() => {
    if (
      isDepthCraftEnabled &&
      buildModeNotification &&
      !hasAutoTriggeredRef.current &&
      !hasTenantModal &&
      !isCraftAnimationDisabled
    ) {
      hasAutoTriggeredRef.current = true;
      setShowIntroAnimation(true);
    }
  }, [
    buildModeNotification,
    isDepthCraftEnabled,
    hasTenantModal,
    isCraftAnimationDisabled,
  ]);

  // Dismiss the build mode notification
  const dismissBuildModeNotification = useCallback(async () => {
    if (!buildModeNotification) return;
    try {
      await dismissNotification(buildModeNotification.id);
      mutateNotifications();
    } catch (error) {
      console.error("Error dismissing notification:", error);
    }
  }, [buildModeNotification, mutateNotifications]);

  const { user, isAdmin } = useUser();
  const activeSidebarTab = useAppPosition();
  const defaultAppMode =
    (user?.preferences?.default_app_mode?.toLowerCase() as "chat" | "search") ??
    "chat";

  const handleShowBuildIntro = useCallback(() => {
    setShowIntroAnimation(true);
  }, []);

  return (
    <>
      {/* Intro animation overlay */}
      <AnimatePresence>
        {showIntroAnimation && (
          <motion.div
            className="fixed inset-0 z-9999"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.5 }}
          >
            <BuildModeIntroBackground />
            <BuildModeIntroContent
              onClose={() => {
                setShowIntroAnimation(false);
                dismissBuildModeNotification();
              }}
              onTryBuildMode={() => {
                setShowIntroAnimation(false);
                dismissBuildModeNotification();
                router.push(CRAFT_PATH);
              }}
            />
          </motion.div>
        )}
      </AnimatePresence>

      <SidebarLayouts.Root foldable>
        <BrandedSidebarHeader>
          <div data-testid="AppSidebar/new-session">
            <SidebarTab
              icon={SvgPlus}
              href={activeSidebarTab.linkToNewSession().href}
              selected={activeSidebarTab.isNewSession()}
              onClick={(event) => {
                // Already on a new session: start it over instead.
                if (activeSidebarTab.isNewSession()) {
                  setAppMode(defaultAppMode);
                  reset();
                  return;
                }
                activeSidebarTab.linkToNewSession().onClick(event);
              }}
            >
              {t("appSidebar.newSession.label")}
            </SidebarTab>
          </div>
          {reviewAvailability.data?.enabled ? (
            <SidebarTab icon={SvgSearchMenu} href="/app/reviews">
              {reviewLabels("title")}
            </SidebarTab>
          ) : null}
          <ChatSearchCommandMenu
            trigger={(open, isOpen) => (
              <SidebarTab icon={SvgSearchMenu} selected={isOpen} onClick={open}>
                {t("appSidebar.searchChats.label")}
              </SidebarTab>
            )}
          />
          {(isDepthCraftEnabled || isDepthCraftUpsell) && (
            <div data-testid="AppSidebar/build">
              <Disabled
                disabled={!hasCraftTier}
                // Only admins can open billing, so others are told to ask one.
                tooltip={
                  isAdmin
                    ? plans[Tier.BUSINESS].tooltip
                    : tCraftUpgrade("userDescription")
                }
              >
                <SidebarTab
                  icon={SvgDevKit}
                  href={hasCraftTier ? CRAFT_PATH : undefined}
                  onClick={
                    hasCraftTier
                      ? () => track(AnalyticsEvent.CLICKED_CRAFT_IN_SIDEBAR)
                      : undefined
                  }
                  rightChildren={
                    isDepthCraftUpsell ? (
                      <PlanTag plan={Tier.BUSINESS} />
                    ) : (
                      <Section
                        flexDirection="row"
                        gap={1.5}
                        width="fit"
                        height="fit"
                      >
                        {unviewedTaskCount > 0 && (
                          <UnseenMarker label={tTasks("unviewedResults")} />
                        )}
                        <BetaTag />
                      </Section>
                    )
                  }
                >
                  {t("appSidebar.craft.label")}
                </SidebarTab>
              </Disabled>
            </div>
          )}
        </BrandedSidebarHeader>

        <SidebarLayouts.Body scrollKey="app-sidebar">
          <RecentsSection
            chatSessions={chatSessions}
            isLoading={isLoadingChatSessions}
            hasMore={hasMore}
            isLoadingMore={isLoadingMore}
            onLoadMore={loadMore}
          />
        </SidebarLayouts.Body>

        <SidebarLayouts.Footer>
          <div>
            <AccountPopover
              onShowBuildIntro={
                isDepthCraftEnabled ? handleShowBuildIntro : undefined
              }
            />
          </div>
        </SidebarLayouts.Footer>
      </SidebarLayouts.Root>
    </>
  );
}
