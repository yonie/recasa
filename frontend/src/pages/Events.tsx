import { useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, MapPin } from "lucide-react";
import { api, collageUrl, thumbnailUrl, type EventSummary } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { CollageButton } from "../components/CollagePopover";
import {
  BackButton,
  EmptyState,
  ErrorState,
  PageHeader,
  PageSpinner,
  PageTitle,
  PhotoListLayout,
} from "../components/Page";
import { useScrollRestore } from "../hooks/useScrollRestore";
import { useCardThumbSize } from "../lib/gridLayout";
import { plural } from "../lib/format";

// Event detail view (route: /events/:eventId)
export function EventDetail() {
  const { eventId } = useParams<{ eventId: string }>();
  const navigate = useNavigate();
  const id = Number(eventId);

  const eventQuery = useQuery({
    queryKey: queryKeys.event(id),
    queryFn: () => api.getEvent(id),
    enabled: !!eventId,
  });
  const photosQuery = useQuery({
    queryKey: queryKeys.eventPhotos(id),
    queryFn: () => api.getEventPhotos(id, { page_size: 200 }),
    enabled: !!eventId,
  });
  const event = eventQuery.data;
  const photos = photosQuery.data?.items ?? [];

  if (eventQuery.isLoading || photosQuery.isLoading) return <PageSpinner />;
  if (!event) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <p>Event not found</p>
      </div>
    );
  }
  if (photosQuery.error) return <ErrorState error={photosQuery.error} />;

  return (
    <PhotoListLayout
      photos={photos}
      header={
        <PageHeader className="flex items-center gap-3">
          <BackButton onClick={() => navigate("/events")} />
          <div>
            <h1 className="text-lg font-semibold">{event.name}</h1>
            <div className="flex items-center gap-3 text-xs text-gray-400">
              {event.location && (
                <span className="flex items-center gap-1">
                  <MapPin className="w-3 h-3" />
                  {event.location}
                </span>
              )}
              <span>
                {event.photo_count} {plural(event.photo_count, "photo")}
              </span>
            </div>
            {event.summary && <p className="text-sm text-gray-500 mt-1">{event.summary}</p>}
          </div>
          <div className="ml-auto">
            <CollageButton
              url={collageUrl.event(event.event_id)}
              label={`${event.name}: Collage`}
              photoCount={photos.length}
            />
          </div>
        </PageHeader>
      }
    />
  );
}

// Events list view (route: /events)
export function Events() {
  const { scrollRef, restoreScroll } = useScrollRestore("events");
  const coverSize = useCardThumbSize(EVENT_COLUMNS, 16, 16);

  const { data: events = [], isLoading, error } = useQuery({
    queryKey: queryKeys.events,
    queryFn: () => api.getEvents({ page_size: 1000 }),
  });

  // Restore scroll position after events load
  useEffect(() => {
    if (!isLoading && events.length > 0) {
      restoreScroll();
    }
  }, [isLoading, events.length, restoreScroll]);

  if (isLoading) return <PageSpinner />;
  if (error) return <ErrorState error={error} />;
  if (events.length === 0) {
    return (
      <EmptyState
        icon={CalendarDays}
        title="No events detected yet"
        hint="Events are auto-detected from photo timestamps and locations"
      />
    );
  }

  return (
    <div ref={scrollRef} className="overflow-y-auto h-full">
      <PageHeader>
        <PageTitle count={`${events.length} ${plural(events.length, "event")}`}>Events</PageTitle>
      </PageHeader>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 p-4">
        {events.map((event) => (
          <EventCard key={event.event_id} event={event} coverSize={coverSize} />
        ))}
      </div>
    </div>
  );
}

// Columns of the card grid below (grid-cols-1 sm:grid-cols-2 lg:grid-cols-3,
// gap-4 p-4) at base, sm, md, lg and xl, to size the cover thumbnails.
const EVENT_COLUMNS = [1, 2, 2, 3, 3];

function EventCard({ event, coverSize }: { event: EventSummary; coverSize: number }) {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate(`/events/${event.event_id}`)}
      className="bg-white rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow border border-gray-100 text-left group"
    >
      {/* Cover photo */}
      <div className="aspect-video bg-gray-100 relative overflow-hidden">
        {event.cover_photo ? (
          // Lazy: the list holds every event, and eager covers for all of them
          // kept the Pi busy for many seconds on each visit. Sized to the card:
          // 600 px on a standard screen, 1200 px where the density needs it.
          <img
            src={thumbnailUrl(event.cover_photo.file_hash, coverSize)}
            alt=""
            loading="lazy"
            decoding="async"
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <CalendarDays className="w-12 h-12 text-gray-300" />
          </div>
        )}
        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent p-3">
          <p className="text-white text-sm font-medium">{event.name}</p>
        </div>
      </div>

      {/* Info */}
      <div className="p-3">
        <div className="flex items-center justify-between text-xs text-gray-500">
          <div className="flex items-center gap-2">
            {event.location && (
              <span className="flex items-center gap-1">
                <MapPin className="w-3 h-3" />
                {event.location}
              </span>
            )}
          </div>
          <span>{event.photo_count} photos</span>
        </div>
        {event.summary && <p className="text-xs text-gray-600 mt-1.5 line-clamp-2">{event.summary}</p>}
        {event.start_date && (
          <p className="text-xs text-gray-400 mt-1">{formatDateRange(event.start_date, event.end_date)}</p>
        )}
      </div>
    </button>
  );
}

function formatDateRange(start: string, end: string | null): string {
  const startDate = new Date(start);
  const full: Intl.DateTimeFormatOptions = { year: "numeric", month: "short", day: "numeric" };
  if (!end) return startDate.toLocaleDateString(undefined, full);

  const endDate = new Date(end);
  if (startDate.toDateString() === endDate.toDateString()) {
    return startDate.toLocaleDateString(undefined, full);
  }
  return `${startDate.toLocaleDateString(undefined, { month: "short", day: "numeric" })} - ${endDate.toLocaleDateString(undefined, full)}`;
}
