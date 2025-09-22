// src/types/index.ts

/**
 * Interface for the source site information used during cross-seeding.
 */
export interface ISourceInfo {
  /**
   * The site's nickname, e.g., 'MTeam'.
   * This is used for display purposes.
   */
  name: string;

  /**
   * The site's internal identifier, e.g., 'mteam'.
   * This is used for API calls.
   */
  site: string;

  /**
   * The torrent ID on the source site.
   */
  torrentId: string;
}
