// icons.tsx -- hand-drawn stroke icons in the style of pen-and-ink
// marginalia. All inherit currentColor; slightly irregular paths on
// purpose -- they should look drawn, not extruded.

const base = {
    width: 20,
    height: 20,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
};

export const QuillIcon = () => (
    <svg {...base} aria-hidden="true">
        <path d="M19 4c-5 .5-9.5 3.5-12 8.5L5.5 18l1.2-.3c5.5-1.5 9.8-5.7 11.6-11.2L19 4z"/>
        <path d="M5.5 18 4 20.5"/>
        <path d="M9.5 14.5c2-.3 4-1.4 5.6-3"/>
    </svg>
);

export const PeakIcon = () => (
    <svg {...base} aria-hidden="true">
        <path d="M3 19.5 9.2 7l3.1 6.2L14.8 9l6 10.5z"/>
        <path d="m7.6 10.4 1.6 1.4 1.4-1.6"/>
    </svg>
);

export const RiverIcon = () => (
    <svg {...base} aria-hidden="true">
        <path d="M4 5c3 1.5 1.5 4.5 4.5 6S13 13 11.5 16s2 4 4.5 3"/>
        <path d="M16.5 4.5c2 .8 3 2.7 2.8 4.7"/>
        <circle cx="4" cy="5" r="1"/>
    </svg>
);

export const SurveyIcon = () => (
    <svg {...base} aria-hidden="true">
        <path d="M12 21V6"/>
        <path d="M12 6c2.8-2 5.4-1.8 7.5-.4-1.6 1.8-4.4 2.4-7.5 1.6"/>
        <path d="M8.5 21h7"/>
        <path d="M9.8 10.5 12 12.5l2.2-2"/>
    </svg>
);

export const RunIcon = () => (
    <svg {...base} aria-hidden="true">
        <path d="M12 3.5c1 2.5 2.5 4 5.5 4.5-2 2-3 4-2.5 7-2.5-1-5-1-7.5.5.5-3-.5-5.5-2.5-7.5 3-.5 5.5-2 7-4.5z"/>
        <circle cx="12" cy="11" r="1.2"/>
    </svg>
);

export const EyeIcon = ({closed = false}: { closed?: boolean }) =>
    closed ? (
        <svg {...base} width={16} height={16} aria-hidden="true">
            <path d="M4 12c2.5 3 5.2 4.5 8 4.5s5.5-1.5 8-4.5"/>
            <path d="m7 15.5-1.5 2M12 16.8V19m5-3.5 1.5 2"/>
        </svg>
    ) : (
        <svg {...base} width={16} height={16} aria-hidden="true">
            <path d="M4 12c2.5-3.2 5.2-4.8 8-4.8s5.5 1.6 8 4.8c-2.5 3.2-5.2 4.8-8 4.8S6.5 15.2 4 12z"/>
            <circle cx="12" cy="12" r="2"/>
        </svg>
    );

export const UndoIcon = () => (
    <svg {...base} width={16} height={16} aria-hidden="true">
        <path d="M7.5 7 4 10.5 7.5 14"/>
        <path d="M4 10.5h9.5a5 5 0 0 1 .3 10H10"/>
    </svg>
);

export const RedoIcon = () => (
    <svg {...base} width={16} height={16} aria-hidden="true">
        <path d="m16.5 7 3.5 3.5-3.5 3.5"/>
        <path d="M20 10.5h-9.5a5 5 0 0 0-.3 10H14"/>
    </svg>
);

export const CompassRose = () => (
    <svg
        width="84"
        height="84"
        viewBox="0 0 100 100"
        aria-hidden="true"
        style={{opacity: 0.85}}
    >
        <g stroke="currentColor" fill="none" strokeWidth="1.2">
            <circle cx="50" cy="50" r="30"/>
            <circle cx="50" cy="50" r="24" strokeDasharray="2.5 3.5"/>
        </g>
        <g fill="currentColor">
            <path d="M50 8 56 44 50 50 44 44z"/>
            <path d="M50 92 55 56 50 50 45 56z" opacity="0.55"/>
            <path d="M8 50 44 45 50 50 44 55z" opacity="0.55"/>
            <path d="M92 50 56 45 50 50 56 55z" opacity="0.55"/>
        </g>
        <text
            x="50"
            y="6.5"
            textAnchor="middle"
            fontSize="11"
            fill="currentColor"
            fontFamily="inherit"
        >
            N
        </text>
    </svg>
);