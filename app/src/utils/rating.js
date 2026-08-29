// Rating is stored/transmitted as a 0-10 integer scale (Calibre convention),
// but the UI shows plain 5-star widgets (no half stars). These helpers convert
// between the two, rounding to the nearest whole star for display.

export function toStars(rating) {
    if (rating === null || rating === undefined || isNaN(rating)) return 0;
    return Math.round(Number(rating) / 2);
}

export function fromStars(stars) {
    if (stars === null || stars === undefined || isNaN(stars)) return 0;
    return Number(stars) * 2;
}
