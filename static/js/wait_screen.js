import {getGamestateRecord, init_pocketbase} from "./multiplayer.js";

await init_pocketbase().then(r => console.log(r));


let state = (await getGamestateRecord()).state;

console.log("Gamestate is: ", state);

if (state === "playing") {
    window.location.href = "/game";
}