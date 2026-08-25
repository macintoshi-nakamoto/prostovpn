import { Empty, Loading } from "./primitives";

export function Table({ columns, rows, keyOf, onRowClick, sort, onSort, loading, empty }) {
  if (loading) return <Loading />;
  if (!rows.length) return <Empty>{empty}</Empty>;

  return (
    <div className="gd-table-wrap">
      <table className="gd-table">
        <thead>
          <tr>
            {columns.map((col) => {
              const sortable = Boolean(col.sortKey && onSort);
              const active = sort && sort.key === col.sortKey;
              return (
                <th
                  key={col.key}
                  className={[col.num ? "num" : "", sortable ? "sortable" : ""].filter(Boolean).join(" ")}
                  style={col.width ? { width: col.width } : undefined}
                  onClick={sortable ? () => onSort(col.sortKey) : undefined}
                >
                  {col.title}
                  {active && <span style={{ marginLeft: 4 }}>{sort.dir === "asc" ? "↑" : "↓"}</span>}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={keyOf(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              style={onRowClick ? undefined : { cursor: "default" }}
            >
              {columns.map((col) => (
                <td key={col.key} className={col.num ? "num" : undefined}>
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CellName({ title, sub }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div className="gd-cellname" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {title}
      </div>
      {sub && <div className="gd-cellsub">{sub}</div>}
    </div>
  );
}
