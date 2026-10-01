import { formatTime, formatDuration } from "@/lib/meetingTime";

interface MeetingInfoProps {
  title: string;
  startTime: string;
  endTime: string;
  location: string;
}

export function MeetingInfo({ title, startTime, endTime, location }: MeetingInfoProps) {
  return (
    <div className="stack" style={{ gap: 10 }}>
      <h2>{title}</h2>
      <dl className="kv">
        <dt>시간</dt>
        <dd>{formatTime(startTime)} ~ {formatTime(endTime)} <span className="subtle">({formatDuration(startTime, endTime)})</span></dd>
        <dt>장소</dt>
        <dd>{location || "미지정"}</dd>
      </dl>
    </div>
  );
}
