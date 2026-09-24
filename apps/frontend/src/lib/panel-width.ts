/**
 * The panel's width choice (ADR-057), read by the layout on the server. A
 * plain module: a constant exported from a "use client" file reaches a server
 * component as a client reference, not as its value.
 */
export const PANEL_WIDTH_COOKIE = "panel-width";
