import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, type EventSummary, type PhotoSummary, thumbnailUrl } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { useScrollRestore } from "../hooks/useScrollRestore";
import { Loader2, CalendarDays, ArrowLeft, MapPin } from "lucide-react";

// Event detail view (route: /events/:eventId)
export function EventDetail() {
  const { eventId } = useParams<{ eventId: string }>();
  const navigate = useNavigate();
  const [event, setEvent] = useState<EventSummary | null>(null);
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      if (!eventId) return;
      try {
        setLoading(true);
        const [eventData, photosData] = await Promise.all([
          api.getEvent(Number(eventId)),
          api.getEventPhotos(Number(eventId), { page_size: 200 }),
        ]);
        setEvent(eventData);
        setPhotos(photosData.items);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [eventId]);

  const handlePhotoClick = useCallback(
    async (photo: PhotoSummary, index: number) => {
      try {
        const detail = await api.getPhoto(photo.file_hash);
        openViewer(detail, photos, index);
      } catch {
        // ignore
      }
    },
    [openViewer, photos]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  if (!event) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <p>Event not found</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
        <button
          onClick={() => navigate("/events")}
          className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
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
              {event.photo_count} photo{event.photo_count !== 1 ? "s" : ""}
            </span>
          </div>
        </div>
      </div>

      <PhotoGrid photos={photos} onPhotoClick={handlePhotoClick} />
    </div>
  );
}

// Events list view (route: /events)
export function Events() {
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const { scrollRef, restoreScroll } = useScrollRestore("events");

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const data = await api.getEvents({ page_size: 1000 });
        setEvents(data);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Restore scroll position after events load
  useEffect(() => {
    if (!loading && events.length > 0) {
      restoreScroll();
    }
  }, [loading, events.length, restoreScroll]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
        <CalendarDays className="w-12 h-12 text-gray-300" />
        <p className="text-lg">No events detected yet</p>
        <p className="text-sm">Events are auto-detected from photo timestamps and locations</p>
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100">
        <h1 className="text-lg font-semibold">
          Events
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {events.length} event{events.length !== 1 ? "s" : ""}
          </span>
        </h1>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 p-4">
        {events.map((event) => (
          <button
            key={event.event_id}
            onClick={() => navigate(`/events/${event.event_id}`)}
            className="bg-white rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow border border-gray-100 text-left group"
          >
            {/* Cover photo */}
            <div className="aspect-video bg-gray-100 relative overflow-hidden">
              {event.cover_photo ? (
                <img
                  src={thumbnailUrl(event.cover_photo.file_hash, 1200)}
                  alt=""
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
              {event.start_date && (
                <p className="text-xs text-gray-400 mt-1">
                  {formatDateRange(event.start_date, event.end_date)}
                </p>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function formatDateRange(start: string, end: string | null): string {
  const startDate = new Date(start);
  if (!end) {
    return startDate.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  const endDate = new Date(end);
  const sameDay =
    startDate.getFullYear() === endDate.getFullYear() &&
    startDate.getMonth() === endDate.getMonth() &&
    startDate.getDate() === endDate.getDate();

  if (sameDay) {
    return startDate.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  return `${startDate.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  })} - ${endDate.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })}`;
}
