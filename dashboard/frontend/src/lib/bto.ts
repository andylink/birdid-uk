/**
 * Visual style constants for BTO/BoCC species metadata.
 * The underlying data now comes from the species_info DB table via the API.
 */

/** Inline hex colours for UK BoCC status dots. */
export const BOCC_COLOR: Record<string, string> = {
	Red:   '#ef4444',
	Amber: '#f59e0b',
	Green: '#22c55e',
};

/** Background + text colour for species_status pills. */
export const SPECIES_STATUS_STYLE: Record<string, { bg: string; text: string }> = {
	'Common':    { bg: 'rgba(100,116,139,0.25)', text: '#94a3b8' },
	'Scarce':    { bg: 'rgba(234,179,8,0.20)',   text: '#eab308' },
	'Rare':      { bg: 'rgba(249,115,22,0.20)',  text: '#f97316' },
	'Very rare': { bg: 'rgba(239,68,68,0.20)',   text: '#ef4444' },
};

/** One unique colour per taxonomic group_name. */
export const GROUP_BADGE_COLORS: Record<string, string> = {
	'Accentors':             '#96dc2c',
	'Auks':                  '#2c72dc',
	'Bee-eaters':            '#2cdca1',
	'Buntings':              '#dc2cbf',
	'Bustards':              '#dc9c2c',
	'Cranes':                '#6d2cdc',
	'Crows':                 '#2c55dc',
	'Cuckoos':               '#55dc2c',
	'Dippers':               '#2caddc',
	'Divers':                '#2c67dc',
	'Falcons':               '#dc492c',
	'Finches':               '#dc2cdc',
	'Flycatchers & Chats':   '#dc3e2c',
	'Game Birds':            '#dc842c',
	'Goldcrests':            '#2cdc32',
	'Grebes':                '#2c93dc',
	'Gulls & Terns':         '#2cb9dc',
	'Herons & Egrets':       '#2cdccb',
	'Hoopoe':                '#dc6d2c',
	'Ibises & Spoonbills':   '#dc2c67',
	'Kingfishers':           '#2c7edc',
	'Larks':                 '#d6dc2c',
	'New World Passerines':  '#dc2c49',
	'Nightjars':             '#5b2cdc',
	'Nuthatches':            '#2c8adc',
	'Orioles':               '#dcbf2c',
	'Owls':                  '#a12cdc',
	'Parakeets':             '#6ddc2c',
	'Pigeons & Doves':       '#dccb2c',
	'Rails & Crakes':        '#2cdcb9',
	'Raptors':               '#dc2c2c',
	'Rollers':               '#2cdcdc',
	'Sandgrouse':            '#dcb32c',
	'Seabirds':              '#2c4fdc',
	'Shrikes':               '#dc612c',
	'Skuas':                 '#dc552c',
	'Sparrows':              '#dca72c',
	'Starlings':             '#bf2cdc',
	'Storks':                '#dc2c7e',
	'Swallows & Martins':    '#2c2cdc',
	'Swifts':                '#432cdc',
	'Thrushes':              '#dc782c',
	'Tits':                  '#2ccbdc',
	'Treecreepers':          '#2cdc6d',
	'Waders':                '#2cdc90',
	'Wagtails & Pipits':     '#addc2c',
	'Warblers':              '#2cdc49',
	'Waxwings':              '#dc2ca1',
	'Wildfowl':              '#2ca1dc',
	'Woodpeckers':           '#84dc2c',
	'Wrens':                 '#dc902c',
};

/** Hex badge colour for a group_name; falls back to slate if unknown. */
export function groupBadgeColor(groupName: string | null | undefined): string {
	return (groupName && GROUP_BADGE_COLORS[groupName]) ?? '#64748b';
}

/** Derive a display code from BTO codes or fall back to initials. */
export function speciesInitials(
	name: string,
	bto5: string | null | undefined,
	bto2: string | null | undefined,
): string {
	if (bto5?.trim()) return bto5.trim();
	if (bto2?.trim()) return bto2.trim();
	const words = name.trim().split(/\s+/).filter(Boolean);
	if (words.length === 1) return name.substring(0, 2).toUpperCase();
	return (words[0][0] + words[1][0]).toUpperCase();
}
