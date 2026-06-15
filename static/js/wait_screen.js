import {getGamestateRecord, initSubscriptions} from "./multiplayer.js";

await initSubscriptions();

let state = (await getGamestateRecord()).state;

console.log("Gamestate is: ", state);

if (state === "playing") {
    window.location.href = "/game";
}