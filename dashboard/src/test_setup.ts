// jsdom has <dialog> but not its methods, so the tests open and close it the way
// a browser would, without the browser's top layer.
HTMLDialogElement.prototype.showModal = function showModal(
  this: HTMLDialogElement,
) {
  this.open = true;
};
HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
  this.open = false;
};
